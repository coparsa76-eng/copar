# -*- coding: utf-8 -*-
"""
MÓDULO DE VENDAS RÁPIDAS - Versão Web (compatível com app.py existente)
Mantém os mesmos nomes de classes e variedades do sistema original
"""

from flask import render_template_string, jsonify, request, session
import psycopg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

# Constantes (mesmas do sistema Tkinter)
TIPOS_ALHO = ['Ito', 'Chonan', 'São Valentim', 'Tratado', 'Semente']
CLASSES = ['Indústria', 'Classe 2', 'Classe 3', 'Classe 4', 'Classe 5', 'Classe 6', 'Classe 7']
TIPOS_ESTOQUE = ['Classificação', 'Banca', 'Toletagem']

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return None

def verificar_acesso():
    if 'produtor_id' not in session:
        return False
    return session.get('tipo') in ('gerente', 'superadmin')

def buscar_estoque_disponivel(tipo_alho, classe, local_estoque):
    """Busca todos os produtores com estoque disponível"""
    conn = conectar_banco()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.nome, p.matricula, 
                   COALESCE(SUM(e.peso), 0) as peso_total,
                   COALESCE(SUM(e.horas_banca), 0) as horas_banca
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.tipo_alho = %s 
              AND e.classe = %s 
              AND e.local_estoque = %s
              AND e.peso > 0
            GROUP BY p.id, p.nome, p.matricula
            HAVING COALESCE(SUM(e.peso), 0) > 0
            ORDER BY p.nome
        """, (tipo_alho, classe, local_estoque))
        
        result = []
        for row in cur.fetchall():
            result.append({
                'id': row[0],
                'nome': row[1],
                'matricula': row[2],
                'peso_disponivel': float(row[3]),
                'horas_banca': float(row[4] or 0)
            })
        
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque: {e}")
        return []

def registrar_venda_rapida(produtor_id, tipo_alho, classe, local_origem, peso, valor_kg):
    """Registra venda com baixa no estoque (mesma lógica do Tkinter)"""
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    
    try:
        cur = conn.cursor()
        
        # Verificar estoque disponível
        cur.execute("""
            SELECT COALESCE(SUM(peso), 0), COALESCE(SUM(horas_banca), 0)
            FROM estoque
            WHERE produtor_id = %s 
              AND tipo_alho = %s 
              AND classe = %s 
              AND local_estoque = %s 
              AND peso > 0
        """, (produtor_id, tipo_alho, classe, local_origem))
        
        disp, horas_total = cur.fetchone()
        disp = float(disp)
        
        if disp < peso:
            raise ValueError(f"Estoque insuficiente! Disponível: {disp:.2f} Kg")
        
        # Calcular valores
        valor_total = peso * valor_kg
        
        # Buscar descontos padrão
        cur.execute("SELECT valor FROM configuracoes WHERE chave = 'descontos_padrao'")
        row = cur.fetchone()
        if row:
            import json
            descontos = json.loads(row[0])
        else:
            descontos = {
                'fundo_rural_percent': 2.0,
                'comissao_percent': 1.5,
                'valor_hora_banca': 2.0,
                'sacaria_percent': 1.0,
                'icms_percent': 12.0,
                'caixa_percent': 0.5
            }
        
        # Calcular descontos (igual ao Tkinter)
        proporcao = peso / disp if disp > 0 else 0
        horas_usadas = horas_total * proporcao
        
        desconto_fr = valor_total * descontos.get('fundo_rural_percent', 0) / 100
        desconto_com = valor_total * descontos.get('comissao_percent', 0) / 100
        desconto_hb = horas_usadas * descontos.get('valor_hora_banca', 0)
        desconto_sac = valor_total * descontos.get('sacaria_percent', 0) / 100
        desconto_icms = valor_total * descontos.get('icms_percent', 0) / 100
        desconto_cx = valor_total * descontos.get('caixa_percent', 0) / 100
        
        valor_produtor = valor_total - desconto_fr - desconto_com - desconto_hb - desconto_sac - desconto_icms - desconto_cx
        
        if valor_produtor < 0:
            raise ValueError("Valor do produtor negativo após descontos!")
        
        # Registrar venda
        cur.execute("""
            INSERT INTO vendas (
                produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor,
                desconto_fundo_rural, desconto_comissao, desconto_hora_banca,
                desconto_sacaria, desconto_icms, desconto_caixa,
                comprador, origem_estoque, status_pagamento
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor,
            desconto_fr, desconto_com, desconto_hb, desconto_sac, desconto_icms, desconto_cx,
            'Venda Rápida', local_origem, 'Pendente'
        ))
        
        venda_id = cur.fetchone()[0]
        
        # Registrar crédito do produtor
        cur.execute("""
            INSERT INTO creditos_produtor (produtor_id, venda_id, valor_credito, saldo)
            VALUES (%s, %s, %s, %s)
        """, (produtor_id, venda_id, valor_produtor, valor_produtor))
        
        # Dar baixa no estoque (FIFO)
        cur.execute("""
            SELECT id, peso FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s 
              AND local_estoque = %s AND peso > 0
            ORDER BY data_registro, id
            FOR UPDATE
        """, (produtor_id, tipo_alho, classe, local_origem))
        
        rows = cur.fetchall()
        restante = peso
        
        for estoque_id, peso_estoque in rows:
            if restante <= 0:
                break
            peso_estoque = float(peso_estoque)
            if restante >= peso_estoque - 0.001:
                cur.execute("DELETE FROM estoque WHERE id = %s", (estoque_id,))
                restante -= peso_estoque
            else:
                cur.execute("UPDATE estoque SET peso = %s WHERE id = %s", 
                           (round(peso_estoque - restante, 4), estoque_id))
                restante = 0
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Buscar nome do produtor para mensagem
        nome_produtor = ""
        conn2 = conectar_banco()
        if conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT nome FROM produtores WHERE id = %s", (produtor_id,))
            row = cur2.fetchone()
            if row:
                nome_produtor = row[0]
            cur2.close()
            conn2.close()
        
        return {
            'sucesso': True,
            'mensagem': f'✅ Venda #{venda_id} registrada!\nProdutor: {nome_produtor}\nPeso: {peso:.2f} Kg\nValor: R$ {valor_total:.2f}\nLíquido produtor: R$ {valor_produtor:.2f}',
            'venda_id': venda_id,
            'valor_produtor': valor_produtor
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro ao registrar venda: {e}")
        return {'sucesso': False, 'mensagem': f'❌ Erro: {str(e)}'}

# ============================================
# HTML RESPONSIVO (funciona em celular)
# ============================================

HTML_VENDAS_RAPIDAS = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>COPAR - Vendas Rápidas</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: 'DM Sans', sans-serif;
            background: #f2f5f0;
            color: #1a2e19;
            padding: 16px;
            padding-bottom: 32px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        /* Header */
        .header {
            background: linear-gradient(135deg, #2a5c28 0%, #1e4520 100%);
            color: white;
            padding: 20px;
            border-radius: 16px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .header h1 {
            font-size: 1.5rem;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .header p {
            font-size: 0.85rem;
            opacity: 0.9;
        }
        
        /* Cards */
        .card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        
        .card h2 {
            color: #2a5c28;
            font-size: 1.1rem;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e8f2e7;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        /* Formulário */
        .form-group {
            margin-bottom: 16px;
        }
        
        label {
            display: block;
            font-size: 0.8rem;
            font-weight: 600;
            color: #6b7c6a;
            margin-bottom: 6px;
        }
        
        select, input {
            width: 100%;
            padding: 12px;
            border: 1.5px solid #dde8db;
            border-radius: 12px;
            font-family: 'DM Sans', sans-serif;
            font-size: 1rem;
            background: white;
            transition: all 0.2s;
        }
        
        select:focus, input:focus {
            outline: none;
            border-color: #2a5c28;
            box-shadow: 0 0 0 3px rgba(42,92,40,0.1);
        }
        
        /* Botões */
        button {
            background: #2a5c28;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.2s;
            width: 100%;
        }
        
        button:hover {
            background: #3d7a3a;
            transform: scale(1.02);
        }
        
        button:active {
            transform: scale(0.98);
        }
        
        .btn-secondary {
            background: #6b7c6a;
        }
        
        .btn-danger {
            background: #c0392b;
        }
        
        .btn-success {
            background: #1e8449;
        }
        
        .btn-sm {
            padding: 8px 12px;
            font-size: 0.8rem;
            width: auto;
        }
        
        /* Linhas do carrinho */
        .carrinho-item {
            background: #fef9e7;
            border: 1px solid #fdebd0;
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 8px;
        }
        
        .carrinho-info {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 8px;
        }
        
        .carrinho-produtor {
            font-weight: 600;
            color: #2a5c28;
        }
        
        .carrinho-peso {
            font-size: 0.9rem;
            color: #6b7c6a;
        }
        
        .carrinho-valor {
            font-weight: 700;
            color: #1e8449;
        }
        
        /* Total */
        .total-area {
            background: linear-gradient(135deg, #e8f2e7 0%, #d4e4d1 100%);
            padding: 20px;
            border-radius: 16px;
            margin-top: 20px;
        }
        
        .total-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        
        .total-grande {
            font-size: 1.5rem;
            font-weight: 700;
            color: #2a5c28;
        }
        
        /* Alertas */
        .alert {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 20px;
            border-radius: 50px;
            font-size: 0.85rem;
            font-weight: 500;
            z-index: 1000;
            animation: slideDown 0.3s ease-out;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            white-space: nowrap;
        }
        
        @keyframes slideDown {
            from {
                opacity: 0;
                transform: translateX(-50%) translateY(-100%);
            }
            to {
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }
        }
        
        .alert-success {
            background: #1e8449;
            color: white;
        }
        
        .alert-error {
            background: #c0392b;
            color: white;
        }
        
        /* Vazio */
        .vazio {
            text-align: center;
            padding: 40px;
            color: #6b7c6a;
        }
        
        /* Botões de ação */
        .acoes {
            display: flex;
            gap: 12px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .acoes button {
            flex: 1;
        }
        
        /* Responsivo */
        @media (max-width: 600px) {
            body {
                padding: 12px;
            }
            
            .card {
                padding: 16px;
            }
            
            .carrinho-info {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .alert {
                white-space: normal;
                text-align: center;
                max-width: 90%;
            }
        }
        
        /* Loading */
        .loading {
            text-align: center;
            padding: 20px;
            color: #6b7c6a;
        }
        
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid #e8f2e7;
            border-top-color: #2a5c28;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>⚡ Vendas Rápidas</h1>
        <p>Selecione o produto e adicione produtores rapidamente</p>
    </div>
    
    <div id="alert"></div>
    
    <!-- Seleção do Produto -->
    <div class="card">
        <h2>📦 1. Selecione o Produto</h2>
        <div class="form-group">
            <label>🌾 Tipo de Alho</label>
            <select id="tipo_alho">
                <option value="">Selecione...</option>
                {% for tipo in tipos_alho %}
                <option value="{{ tipo }}">{{ tipo }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>📋 Classe</label>
            <select id="classe">
                <option value="">Selecione...</option>
                {% for classe in classes %}
                <option value="{{ classe }}">{{ classe }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>📍 Local de Origem</label>
            <select id="local_origem">
                <option value="">Selecione...</option>
                {% for local in locais %}
                <option value="{{ local }}">{{ local }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>💰 Preço por KG (R$)</label>
            <input type="number" id="preco_kg" step="0.01" placeholder="Ex: 10.50">
        </div>
    </div>
    
    <!-- Lista de Produtores -->
    <div class="card" id="card_produtores" style="display: none;">
        <h2>👥 2. Adicione os Produtores</h2>
        <div id="produtores_lista"></div>
        <button id="btn_adicionar" style="margin-top: 16px;">➕ Adicionar Produtor</button>
    </div>
    
    <!-- Carrinho -->
    <div class="card" id="card_carrinho" style="display: none;">
        <h2>🛒 3. Carrinho de Venda</h2>
        <div id="carrinho_items"></div>
        <div class="total-area">
            <div class="total-row">
                <span>Total da Venda:</span>
                <strong id="total_venda">R$ 0,00</strong>
            </div>
            <div class="total-row">
                <span>Comissão (10%):</span>
                <span id="comissao">R$ 0,00</span>
            </div>
            <div class="total-row">
                <span>Valor ao Produtor:</span>
                <strong id="valor_produtor" style="color: #1e8449;">R$ 0,00</strong>
            </div>
        </div>
        <div class="acoes">
            <button class="btn-success" id="btn_finalizar">✅ FINALIZAR VENDA</button>
            <button class="btn-danger" id="btn_limpar">🗑️ LIMPAR TUDO</button>
        </div>
    </div>
    
    <div class="acoes">
        <button class="btn-secondary" onclick="window.location.href='/gerente'">← Voltar ao Painel</button>
    </div>
</div>

<script>
let carrinho = [];
let produtoresDisponiveis = [];
let currentId = 0;

// Elementos DOM
const tipoAlho = document.getElementById('tipo_alho');
const classe = document.getElementById('classe');
const localOrigem = document.getElementById('local_origem');
const precoKg = document.getElementById('preco_kg');

// Mostrar alerta
function mostrarAlerta(msg, tipo) {
    const alertDiv = document.getElementById('alert');
    alertDiv.innerHTML = `<div class="alert alert-${tipo}">${msg}</div>`;
    setTimeout(() => {
        alertDiv.innerHTML = '';
    }, 3000);
}

// Carregar produtores disponíveis
async function carregarProdutores() {
    const tipo = tipoAlho.value;
    const cls = classe.value;
    const local = localOrigem.value;
    const preco = parseFloat(precoKg.value);
    
    if (!tipo || !cls || !local || !preco) {
        document.getElementById('card_produtores').style.display = 'none';
        return;
    }
    
    mostrarAlerta('🔍 Buscando produtores...', 'success');
    
    try {
        const response = await fetch('/api/vendas-rapido/produtores', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                tipo_alho: tipo,
                classe: cls,
                local_estoque: local
            })
        });
        
        const data = await response.json();
        
        if (data.sucesso) {
            produtoresDisponiveis = data.produtores;
            document.getElementById('card_produtores').style.display = 'block';
            if (produtoresDisponiveis.length === 0) {
                mostrarAlerta('⚠️ Nenhum produtor com estoque disponível!', 'error');
            }
        } else {
            mostrarAlerta(data.mensagem, 'error');
        }
    } catch (error) {
        mostrarAlerta('Erro ao buscar produtores', 'error');
    }
}

// Adicionar linha de produtor
function adicionarLinhaProdutor() {
    if (produtoresDisponiveis.length === 0) {
        mostrarAlerta('⚠️ Nenhum produtor disponível para este produto!', 'error');
        return;
    }
    
    const linhaId = currentId++;
    carrinho.push({
        id: linhaId,
        produtor_id: null,
        produtor_nome: '',
        matricula: '',
        peso: 0,
        peso_disponivel: 0,
        preco: parseFloat(precoKg.value)
    });
    
    renderizarProdutoresLista();
}

// Atualizar produtor na linha
function atualizarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel) {
    const item = carrinho.find(i => i.id === linhaId);
    if (item) {
        item.produtor_id = produtorId;
        item.produtor_nome = nome;
        item.matricula = matricula;
        item.peso_disponivel = pesoDisponivel;
        renderizarProdutoresLista();
    }
}

// Atualizar peso
function atualizarPeso(linhaId, peso) {
    const item = carrinho.find(i => i.id === linhaId);
    if (item) {
        item.peso = parseFloat(peso) || 0;
        if (item.peso > item.peso_disponivel) {
            mostrarAlerta(`⚠️ Peso excede o disponível (${item.peso_disponivel} kg)`, 'error');
            item.peso = item.peso_disponivel;
        }
        renderizarProdutoresLista();
        atualizarResumo();
    }
}

// Remover linha
function removerLinha(linhaId) {
    carrinho = carrinho.filter(i => i.id !== linhaId);
    renderizarProdutoresLista();
    atualizarResumo();
}

// Renderizar lista de produtores
function renderizarProdutoresLista() {
    const container = document.getElementById('produtores_lista');
    
    if (carrinho.length === 0) {
        container.innerHTML = '<div class="vazio">Nenhum produtor adicionado. Clique em "Adicionar Produtor" para começar.</div>';
        return;
    }
    
    let html = '';
    carrinho.forEach((item, idx) => {
        html += `
            <div class="carrinho-item" style="margin-bottom: 16px;">
                <div class="carrinho-info">
                    <span class="carrinho-produtor">👤 Produtor ${idx + 1}</span>
                    <button class="btn-sm btn-danger" onclick="removerLinha(${item.id})">✖ Remover</button>
                </div>
                <div class="form-group">
                    <label>🔍 Buscar Produtor</label>
                    <input type="text" id="busca_${item.id}" placeholder="Digite nome ou matrícula..." 
                           oninput="buscarProdutor(${item.id}, this.value)" style="font-size: 0.9rem;">
                    <div id="resultados_${item.id}" style="display: none; background: white; border: 1px solid #dde8db; border-radius: 8px; max-height: 150px; overflow-y: auto; margin-top: 4px;"></div>
                </div>
                <div class="form-group">
                    <label>👤 Produtor Selecionado</label>
                    <input type="text" id="produtor_${item.id}" value="${item.produtor_nome}" readonly placeholder="Nenhum selecionado" style="background: #f4f9f3;">
                </div>
                <div class="form-group">
                    <label>⚖️ Peso (KG) - Disponível: ${item.peso_disponivel} kg</label>
                    <input type="number" id="peso_${item.id}" step="0.001" value="${item.peso || ''}" 
                           placeholder="Ex: 10.5" onchange="atualizarPeso(${item.id}, this.value)">
                </div>
                <div class="form-group">
                    <label>💰 Subtotal</label>
                    <input type="text" value="R$ ${(item.peso * item.preco).toFixed(2)}" readonly style="background: #f4f9f3; font-weight: 600;">
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    
    // Reaplicar valores de peso
    carrinho.forEach(item => {
        const pesoInput = document.getElementById(`peso_${item.id}`);
        if (pesoInput && item.peso) {
            pesoInput.value = item.peso;
        }
    });
}

// Buscar produtor
let timeouts = {};
function buscarProdutor(linhaId, termo) {
    if (timeouts[linhaId]) clearTimeout(timeouts[linhaId]);
    
    if (termo.length < 2) {
        document.getElementById(`resultados_${linhaId}`).style.display = 'none';
        return;
    }
    
    timeouts[linhaId] = setTimeout(async () => {
        const tipo = tipoAlho.value;
        const cls = classe.value;
        const local = localOrigem.value;
        
        try {
            const response = await fetch('/api/vendas-rapido/buscar-produtor', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    termo: termo,
                    tipo_alho: tipo,
                    classe: cls,
                    local_estoque: local
                })
            });
            
            const data = await response.json();
            
            if (data.sucesso && data.produtores.length > 0) {
                const resultadosDiv = document.getElementById(`resultados_${linhaId}`);
                let html = '<div style="padding: 8px;">';
                data.produtores.forEach(p => {
                    html += `
                        <div style="padding: 10px; cursor: pointer; border-bottom: 1px solid #eee;" 
                             onclick="selecionarProdutor(${linhaId}, ${p.id}, '${p.nome}', '${p.matricula}', ${p.peso_disponivel})">
                            <strong>${p.nome}</strong><br>
                            <small style="color: #6b7c6a;">Matrícula: ${p.matricula} | Disponível: ${p.peso_disponivel} kg</small>
                        </div>
                    `;
                });
                html += '</div>';
                resultadosDiv.innerHTML = html;
                resultadosDiv.style.display = 'block';
            } else {
                document.getElementById(`resultados_${linhaId}`).style.display = 'none';
            }
        } catch (error) {
            console.error('Erro:', error);
        }
    }, 500);
}

// Selecionar produtor
function selecionarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel) {
    document.getElementById(`produtor_${linhaId}`).value = nome;
    document.getElementById(`resultados_${linhaId}`).style.display = 'none';
    document.getElementById(`busca_${linhaId}`).value = matricula;
    
    atualizarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel);
}

// Atualizar resumo do carrinho
function atualizarResumo() {
    const itensValidos = carrinho.filter(i => i.produtor_id && i.peso > 0);
    const total = itensValidos.reduce((sum, i) => sum + (i.peso * i.preco), 0);
    const comissao = total * 0.10;
    const valorProdutor = total - comissao;
    
    document.getElementById('total_venda').innerHTML = `R$ ${total.toFixed(2)}`;
    document.getElementById('comissao').innerHTML = `R$ ${comissao.toFixed(2)}`;
    document.getElementById('valor_produtor').innerHTML = `R$ ${valorProdutor.toFixed(2)}`;
    
    // Mostrar/esconder carrinho
    if (itensValidos.length > 0) {
        document.getElementById('card_carrinho').style.display = 'block';
    } else {
        document.getElementById('card_carrinho').style.display = 'none';
    }
}

// Finalizar venda
async function finalizarVenda() {
    const itensValidos = carrinho.filter(i => i.produtor_id && i.peso > 0);
    
    if (itensValidos.length === 0) {
        mostrarAlerta('⚠️ Adicione pelo menos um produtor com peso válido!', 'error');
        return;
    }
    
    const total = itensValidos.reduce((sum, i) => sum + (i.peso * i.preco), 0);
    
    if (!confirm(`Confirmar venda no valor total de R$ ${total.toFixed(2)}?\n\n${itensValidos.length} produtor(es) envolvido(s).\n\nApós confirmar, o estoque será baixado automaticamente.`)) {
        return;
    }
    
    mostrarAlerta('🔄 Processando venda...', 'success');
    
    try {
        const response = await fetch('/api/vendas-rapido/finalizar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                itens: itensValidos.map(i => ({
                    produtor_id: i.produtor_id,
                    tipo_alho: tipoAlho.value,
                    classe: classe.value,
                    local_origem: localOrigem.value,
                    peso: i.peso,
                    valor_kg: i.preco
                })),
                total_venda: total
            })
        });
        
        const data = await response.json();
        
        if (data.sucesso) {
            mostrarAlerta(data.mensagem, 'success');
            setTimeout(() => {
                window.location.reload();
            }, 3000);
        } else {
            mostrarAlerta(data.mensagem, 'error');
        }
    } catch (error) {
        mostrarAlerta('Erro ao processar venda', 'error');
    }
}

// Limpar tudo
function limparTudo() {
    if (confirm('Limpar toda a venda? Todos os dados serão perdidos.')) {
        carrinho = [];
        currentId = 0;
        renderizarProdutoresLista();
        atualizarResumo();
        tipoAlho.value = '';
        classe.value = '';
        localOrigem.value = '';
        precoKg.value = '';
        document.getElementById('card_produtores').style.display = 'none';
        mostrarAlerta('Carrinho limpo!', 'success');
    }
}

// Event listeners
tipoAlho.addEventListener('change', carregarProdutores);
classe.addEventListener('change', carregarProdutores);
localOrigem.addEventListener('change', carregarProdutores);
precoKg.addEventListener('change', () => {
    if (carrinho.length > 0) {
        carrinho.forEach(item => item.preco = parseFloat(precoKg.value));
        renderizarProdutoresLista();
        atualizarResumo();
    }
});

document.getElementById('btn_adicionar').addEventListener('click', adicionarLinhaProdutor);
document.getElementById('btn_finalizar').addEventListener('click', finalizarVenda);
document.getElementById('btn_limpar').addEventListener('click', limparTudo);
</script>
</body>
</html>
"""

# ============================================
# ROTAS
# ============================================

def registrar_rotas_vendas_rapido(app):
    """Registra todas as rotas do módulo de vendas rápidas"""
    
    @app.route('/vendas/rapido')
    def vendas_rapido():
        """Página principal de vendas rápidas"""
        if not verificar_acesso():
            return "Acesso negado. Área restrita ao gerente.", 403
        
        return render_template_string(HTML_VENDAS_RAPIDAS, 
                                      tipos_alho=TIPOS_ALHO,
                                      classes=CLASSES,
                                      locais=TIPOS_ESTOQUE)
    
    @app.route('/api/vendas-rapido/produtores', methods=['POST'])
    def api_vendas_rapido_produtores():
        """API para buscar produtores com estoque disponível"""
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        tipo_alho = data.get('tipo_alho')
        classe = data.get('classe')
        local_estoque = data.get('local_estoque')
        
        if not all([tipo_alho, classe, local_estoque]):
            return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos'})
        
        produtores = buscar_estoque_disponivel(tipo_alho, classe, local_estoque)
        return jsonify({'sucesso': True, 'produtores': produtores})
    
    @app.route('/api/vendas-rapido/buscar-produtor', methods=['POST'])
    def api_vendas_rapido_buscar():
        """API para buscar produtor específico"""
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        termo = data.get('termo', '').strip()
        tipo_alho = data.get('tipo_alho')
        classe = data.get('classe')
        local_estoque = data.get('local_estoque')
        
        if len(termo) < 2:
            return jsonify({'sucesso': True, 'produtores': []})
        
        conn = conectar_banco()
        if not conn:
            return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão'})
        
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT p.id, p.nome, p.matricula, 
                       COALESCE(SUM(e.peso), 0) as peso_total
                FROM produtores p
                JOIN estoque e ON p.id = e.produtor_id
                WHERE (p.nome ILIKE %s OR p.matricula ILIKE %s)
                  AND e.tipo_alho = %s
                  AND e.classe = %s
                  AND e.local_estoque = %s
                  AND e.peso > 0
                GROUP BY p.id, p.nome, p.matricula
                HAVING COALESCE(SUM(e.peso), 0) > 0
                LIMIT 10
            """, (f'%{termo}%', f'%{termo}%', tipo_alho, classe, local_estoque))
            
            produtores = []
            for row in cur.fetchall():
                produtores.append({
                    'id': row[0],
                    'nome': row[1],
                    'matricula': row[2],
                    'peso_disponivel': float(row[3])
                })
            
            cur.close()
            conn.close()
            return jsonify({'sucesso': True, 'produtores': produtores})
            
        except Exception as e:
            conn.close()
            logger.error(f"Erro ao buscar produtor: {e}")
            return jsonify({'sucesso': False, 'mensagem': str(e)})
    
    @app.route('/api/vendas-rapido/finalizar', methods=['POST'])
    def api_vendas_rapido_finalizar():
        """API para finalizar venda (processa todos os itens)"""
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        itens = data.get('itens', [])
        
        if not itens:
            return jsonify({'sucesso': False, 'mensagem': 'Nenhum item para venda'})
        
        resultados = []
        erros = []
        
        for item in itens:
            resultado = registrar_venda_rapida(
                item['produtor_id'],
                item['tipo_alho'],
                item['classe'],
                item['local_origem'],
                item['peso'],
                item['valor_kg']
            )
            
            if resultado['sucesso']:
                resultados.append(resultado)
            else:
                erros.append(resultado['mensagem'])
        
        if erros:
            return jsonify({
                'sucesso': False,
                'mensagem': f"Erros em {len(erros)} venda(s): {'; '.join(erros[:3])}"
            })
        
        return jsonify({
            'sucesso': True,
            'mensagem': f'✅ {len(resultados)} venda(s) registrada(s) com sucesso!',
            'vendas': resultados
        })
    
    print("✅ Módulo de Vendas Rápidas carregado!")
    print("   📍 Acesse: /vendas/rapido")
