# -*- coding: utf-8 -*-
"""
MÓDULO DE VENDAS RÁPIDAS - Versão Corrigida e Funcional
"""

from flask import render_template_string, jsonify, request, session
import psycopg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

# Constantes
TIPOS_ALHO = ['Ito', 'Chonan', 'São Valentim']
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
    conn = conectar_banco()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.nome, p.matricula, 
                   COALESCE(SUM(e.peso), 0) as peso_total
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
                'peso_disponivel': float(row[3])
            })
        
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque: {e}")
        return []

def registrar_venda_rapida(produtor_id, tipo_alho, classe, local_origem, peso, valor_kg):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    
    try:
        cur = conn.cursor()
        
        # Verificar estoque disponível
        cur.execute("""
            SELECT COALESCE(SUM(peso), 0)
            FROM estoque
            WHERE produtor_id = %s 
              AND tipo_alho = %s 
              AND classe = %s 
              AND local_estoque = %s 
              AND peso > 0
        """, (produtor_id, tipo_alho, classe, local_origem))
        
        disp = float(cur.fetchone()[0])
        
        if disp < peso:
            raise ValueError(f"Estoque insuficiente! Disponível: {disp:.2f} Kg")
        
        # Calcular valores
        valor_total = peso * valor_kg
        comissao = valor_total * 0.10
        valor_produtor = valor_total - comissao
        
        # Registrar venda
        cur.execute("""
            INSERT INTO vendas (
                produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor,
                desconto_comissao, comprador, origem_estoque, status_pagamento
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor,
            comissao, 'Venda Rápida', local_origem, 'Pendente'
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
        
        # Buscar nome do produtor
        nome_produtor = ""
        conn2 = conectar_banco()
        if conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT nome FROM produtores WHERE id = %s", (produtor_id,))
            row_nome = cur2.fetchone()
            if row_nome:
                nome_produtor = row_nome[0]
            cur2.close()
            conn2.close()
        
        return {
            'sucesso': True,
            'mensagem': f'✅ Venda #{venda_id} registrada!\nProdutor: {nome_produtor}\nPeso: {peso:.2f} Kg\nTotal: R$ {valor_total:.2f}\nProdutor recebe: R$ {valor_produtor:.2f}',
            'venda_id': venda_id
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro ao registrar venda: {e}")
        return {'sucesso': False, 'mensagem': f'❌ Erro: {str(e)}'}

# ============================================
# HTML COMPLETO E FUNCIONAL
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
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'DM Sans', sans-serif; background: #f2f5f0; color: #1a2e19; padding: 16px; }
        .container { max-width: 800px; margin: 0 auto; }
        .header { background: linear-gradient(135deg, #2a5c28 0%, #1e4520 100%); color: white; padding: 20px; border-radius: 16px; margin-bottom: 20px; }
        .header h1 { font-size: 1.5rem; margin-bottom: 4px; }
        .header p { font-size: 0.85rem; opacity: 0.9; }
        .card { background: white; border-radius: 16px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .card h2 { color: #2a5c28; font-size: 1.1rem; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #e8f2e7; }
        .form-group { margin-bottom: 16px; }
        label { display: block; font-size: 0.8rem; font-weight: 600; color: #6b7c6a; margin-bottom: 6px; }
        select, input { width: 100%; padding: 12px; border: 1.5px solid #dde8db; border-radius: 12px; font-family: 'DM Sans', sans-serif; font-size: 1rem; }
        select:focus, input:focus { outline: none; border-color: #2a5c28; }
        button { background: #2a5c28; color: white; border: none; padding: 12px 20px; border-radius: 12px; font-weight: 600; font-size: 0.9rem; cursor: pointer; width: 100%; }
        button:hover { background: #3d7a3a; }
        .btn-danger { background: #c0392b; }
        .btn-success { background: #1e8449; }
        .btn-sm { padding: 6px 12px; font-size: 0.75rem; width: auto; }
        .btn-secondary { background: #6b7c6a; }
        .carrinho-item { background: #fef9e7; border: 1px solid #fdebd0; border-radius: 12px; padding: 12px; margin-bottom: 12px; }
        .carrinho-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .total-area { background: #e8f2e7; padding: 16px; border-radius: 12px; margin-top: 16px; }
        .total-row { display: flex; justify-content: space-between; margin-bottom: 8px; }
        .alert { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); padding: 12px 20px; border-radius: 50px; font-size: 0.85rem; z-index: 1000; animation: slideDown 0.3s; white-space: nowrap; }
        @keyframes slideDown { from { opacity: 0; transform: translateX(-50%) translateY(-100%); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
        .alert-success { background: #1e8449; color: white; }
        .alert-error { background: #c0392b; color: white; }
        .vazio { text-align: center; padding: 40px; color: #6b7c6a; }
        .acoes { display: flex; gap: 12px; margin-top: 16px; }
        .acoes button { flex: 1; }
        @media (max-width: 600px) { body { padding: 12px; } .card { padding: 16px; } .alert { white-space: normal; text-align: center; max-width: 90%; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>⚡ Vendas Rápidas</h1>
        <p>Selecione o produto e adicione produtores</p>
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
        <h2>🛒 3. Resumo da Venda</h2>
        <div id="carrinho_items"></div>
        <div class="total-area">
            <div class="total-row"><span>Total da Venda:</span><strong id="total_venda">R$ 0,00</strong></div>
            <div class="total-row"><span>Comissão (10%):</span><span id="comissao">R$ 0,00</span></div>
            <div class="total-row"><span>Valor ao Produtor:</span><strong id="valor_produtor" style="color: #1e8449;">R$ 0,00</strong></div>
        </div>
        <div class="acoes">
            <button class="btn-success" id="btn_finalizar">✅ FINALIZAR VENDA</button>
            <button class="btn-danger" id="btn_limpar">🗑️ LIMPAR TUDO</button>
        </div>
    </div>
    
    <button class="btn-secondary" onclick="window.location.href='/gerente'">← Voltar ao Painel</button>
</div>

<script>
let carrinho = [];
let currentId = 0;

const tipoAlho = document.getElementById('tipo_alho');
const classe = document.getElementById('classe');
const localOrigem = document.getElementById('local_origem');
const precoKg = document.getElementById('preco_kg');

function mostrarAlerta(msg, tipo) {
    const alertDiv = document.getElementById('alert');
    alertDiv.innerHTML = `<div class="alert alert-${tipo}">${msg}</div>`;
    setTimeout(() => { alertDiv.innerHTML = ''; }, 3000);
}

async function carregarProdutores() {
    const tipo = tipoAlho.value;
    const cls = classe.value;
    const local = localOrigem.value;
    const preco = parseFloat(precoKg.value);
    
    if (!tipo || !cls || !local || !preco) {
        document.getElementById('card_produtores').style.display = 'none';
        return;
    }
    
    try {
        const response = await fetch('/api/vendas-rapido/produtores', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ tipo_alho: tipo, classe: cls, local_estoque: local })
        });
        
        const data = await response.json();
        
        if (data.sucesso) {
            window.produtoresDisponiveis = data.produtores;
            document.getElementById('card_produtores').style.display = 'block';
            if (data.produtores.length === 0) {
                mostrarAlerta('⚠️ Nenhum produtor com estoque disponível!', 'error');
            }
        }
    } catch (error) {
        mostrarAlerta('Erro ao buscar produtores', 'error');
    }
}

function adicionarLinhaProdutor() {
    if (!window.produtoresDisponiveis || window.produtoresDisponiveis.length === 0) {
        mostrarAlerta('⚠️ Nenhum produtor disponível!', 'error');
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
    renderizarLista();
}

function atualizarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel) {
    const item = carrinho.find(i => i.id === linhaId);
    if (item) {
        item.produtor_id = produtorId;
        item.produtor_nome = nome;
        item.matricula = matricula;
        item.peso_disponivel = pesoDisponivel;
        renderizarLista();
    }
}

function atualizarPeso(linhaId, peso) {
    const item = carrinho.find(i => i.id === linhaId);
    if (item) {
        item.peso = parseFloat(peso) || 0;
        if (item.peso > item.peso_disponivel) {
            mostrarAlerta(`⚠️ Peso excede o disponível (${item.peso_disponivel} kg)`, 'error');
            item.peso = item.peso_disponivel;
        }
        renderizarLista();
        atualizarResumo();
    }
}

function removerLinha(linhaId) {
    carrinho = carrinho.filter(i => i.id !== linhaId);
    renderizarLista();
    atualizarResumo();
}

function renderizarLista() {
    const container = document.getElementById('produtores_lista');
    
    if (carrinho.length === 0) {
        container.innerHTML = '<div class="vazio">Nenhum produtor adicionado. Clique em "Adicionar Produtor" para começar.</div>';
        return;
    }
    
    let html = '';
    carrinho.forEach((item, idx) => {
        html += `
            <div class="carrinho-item">
                <div class="carrinho-info">
                    <strong>👤 Produtor ${idx + 1}</strong>
                    <button class="btn-sm btn-danger" onclick="removerLinha(${item.id})">✖ Remover</button>
                </div>
                <div class="form-group">
                    <label>🔍 Buscar (nome ou matrícula)</label>
                    <input type="text" id="busca_${item.id}" placeholder="Digite para buscar..." 
                           oninput="buscarProdutor(${item.id}, this.value)">
                    <div id="resultados_${item.id}" style="display:none; background:white; border:1px solid #ddd; border-radius:8px; max-height:150px; overflow-y:auto; margin-top:4px;"></div>
                </div>
                <div class="form-group">
                    <label>👤 Produtor Selecionado</label>
                    <input type="text" id="produtor_${item.id}" value="${item.produtor_nome}" readonly placeholder="Nenhum" style="background:#f4f9f3;">
                </div>
                <div class="form-group">
                    <label>⚖️ Peso (KG) - Disponível: ${item.peso_disponivel} kg</label>
                    <input type="number" id="peso_${item.id}" step="0.001" value="${item.peso || ''}" 
                           placeholder="Ex: 10.5" onchange="atualizarPeso(${item.id}, this.value)">
                </div>
                <div class="form-group">
                    <label>💰 Subtotal</label>
                    <input type="text" value="R$ ${(item.peso * item.preco).toFixed(2)}" readonly style="background:#f4f9f3; font-weight:600;">
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

let timeouts = {};
function buscarProdutor(linhaId, termo) {
    if (timeouts[linhaId]) clearTimeout(timeouts[linhaId]);
    if (termo.length < 2) {
        document.getElementById(`resultados_${linhaId}`).style.display = 'none';
        return;
    }
    
    timeouts[linhaId] = setTimeout(async () => {
        try {
            const response = await fetch('/api/vendas-rapido/buscar-produtor', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    termo: termo,
                    tipo_alho: tipoAlho.value,
                    classe: classe.value,
                    local_estoque: localOrigem.value
                })
            });
            
            const data = await response.json();
            
            if (data.sucesso && data.produtores.length > 0) {
                const div = document.getElementById(`resultados_${linhaId}`);
                let html = '<div style="padding: 8px;">';
                data.produtores.forEach(p => {
                    html += `<div style="padding: 10px; cursor: pointer; border-bottom: 1px solid #eee;" 
                                   onclick="selecionarProdutor(${linhaId}, ${p.id}, '${p.nome}', '${p.matricula}', ${p.peso_disponivel})">
                                <strong>${p.nome}</strong><br>
                                <small>Matrícula: ${p.matricula} | Disponível: ${p.peso_disponivel} kg</small>
                            </div>`;
                });
                html += '</div>';
                div.innerHTML = html;
                div.style.display = 'block';
            }
        } catch (error) {
            console.error(error);
        }
    }, 500);
}

function selecionarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel) {
    document.getElementById(`produtor_${linhaId}`).value = nome;
    document.getElementById(`resultados_${linhaId}`).style.display = 'none';
    document.getElementById(`busca_${linhaId}`).value = matricula;
    atualizarProdutor(linhaId, produtorId, nome, matricula, pesoDisponivel);
}

function atualizarResumo() {
    const itensValidos = carrinho.filter(i => i.produtor_id && i.peso > 0);
    const total = itensValidos.reduce((sum, i) => sum + (i.peso * i.preco), 0);
    const comissao = total * 0.10;
    const valorProdutor = total - comissao;
    
    document.getElementById('total_venda').innerHTML = `R$ ${total.toFixed(2)}`;
    document.getElementById('comissao').innerHTML = `R$ ${comissao.toFixed(2)}`;
    document.getElementById('valor_produtor').innerHTML = `R$ ${valorProdutor.toFixed(2)}`;
    
    // Mostrar resumo do carrinho
    const container = document.getElementById('carrinho_items');
    if (itensValidos.length > 0) {
        let resumoHtml = '<div style="margin-bottom: 16px;">';
        itensValidos.forEach((item, idx) => {
            resumoHtml += `
                <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e8f2e7;">
                    <span><strong>${item.produtor_nome}</strong> (${item.peso.toFixed(2)} kg)</span>
                    <span>R$ ${(item.peso * item.preco).toFixed(2)}</span>
                </div>
            `;
        });
        resumoHtml += '</div>';
        container.innerHTML = resumoHtml;
        document.getElementById('card_carrinho').style.display = 'block';
    } else {
        container.innerHTML = '<div class="vazio">Nenhum item no carrinho</div>';
        document.getElementById('card_carrinho').style.display = 'none';
    }
}

async function finalizarVenda() {
    const itensValidos = carrinho.filter(i => i.produtor_id && i.peso > 0);
    
    if (itensValidos.length === 0) {
        mostrarAlerta('⚠️ Adicione pelo menos um produtor com peso válido!', 'error');
        return;
    }
    
    const total = itensValidos.reduce((sum, i) => sum + (i.peso * i.preco), 0);
    
    if (!confirm(`Confirmar venda no valor total de R$ ${total.toFixed(2)}?\n\n${itensValidos.length} produtor(es) envolvido(s).`)) {
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
                }))
            })
        });
        
        const data = await response.json();
        
        if (data.sucesso) {
            mostrarAlerta(data.mensagem, 'success');
            setTimeout(() => { window.location.reload(); }, 3000);
        } else {
            mostrarAlerta(data.mensagem, 'error');
        }
    } catch (error) {
        mostrarAlerta('Erro ao processar venda', 'error');
    }
}

function limparTudo() {
    if (confirm('Limpar toda a venda?')) {
        carrinho = [];
        currentId = 0;
        renderizarLista();
        atualizarResumo();
        tipoAlho.value = '';
        classe.value = '';
        localOrigem.value = '';
        precoKg.value = '';
        document.getElementById('card_produtores').style.display = 'none';
        mostrarAlerta('Carrinho limpo!', 'success');
    }
}

// Eventos
tipoAlho.addEventListener('change', carregarProdutores);
classe.addEventListener('change', carregarProdutores);
localOrigem.addEventListener('change', carregarProdutores);
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
        if not verificar_acesso():
            return "Acesso negado. Área restrita ao gerente.", 403
        return render_template_string(HTML_VENDAS_RAPIDAS, 
                                      tipos_alho=TIPOS_ALHO,
                                      classes=CLASSES,
                                      locais=TIPOS_ESTOQUE)
    
    @app.route('/api/vendas-rapido/produtores', methods=['POST'])
    def api_vendas_rapido_produtores():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        produtores = buscar_estoque_disponivel(
            data.get('tipo_alho'), data.get('classe'), data.get('local_estoque')
        )
        return jsonify({'sucesso': True, 'produtores': produtores})
    
    @app.route('/api/vendas-rapido/buscar-produtor', methods=['POST'])
    def api_vendas_rapido_buscar():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        termo = data.get('termo', '').strip()
        
        if len(termo) < 2:
            return jsonify({'sucesso': True, 'produtores': []})
        
        conn = conectar_banco()
        if not conn:
            return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão'})
        
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT p.id, p.nome, p.matricula, COALESCE(SUM(e.peso), 0) as peso_total
                FROM produtores p
                JOIN estoque e ON p.id = e.produtor_id
                WHERE (p.nome ILIKE %s OR p.matricula ILIKE %s)
                  AND e.tipo_alho = %s AND e.classe = %s AND e.local_estoque = %s
                  AND e.peso > 0
                GROUP BY p.id, p.nome, p.matricula
                HAVING COALESCE(SUM(e.peso), 0) > 0
                LIMIT 10
            """, (f'%{termo}%', f'%{termo}%', data.get('tipo_alho'), data.get('classe'), data.get('local_estoque')))
            
            produtores = [{'id': r[0], 'nome': r[1], 'matricula': r[2], 'peso_disponivel': float(r[3])} for r in cur.fetchall()]
            cur.close()
            conn.close()
            return jsonify({'sucesso': True, 'produtores': produtores})
        except Exception as e:
            conn.close()
            return jsonify({'sucesso': False, 'mensagem': str(e)})
    
    @app.route('/api/vendas-rapido/finalizar', methods=['POST'])
    def api_vendas_rapido_finalizar():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        itens = data.get('itens', [])
        
        if not itens:
            return jsonify({'sucesso': False, 'mensagem': 'Nenhum item para venda'})
        
        resultados = []
        for item in itens:
            resultado = registrar_venda_rapida(
                item['produtor_id'], item['tipo_alho'], item['classe'],
                item['local_origem'], item['peso'], item['valor_kg']
            )
            if resultado['sucesso']:
                resultados.append(resultado)
            else:
                return jsonify({'sucesso': False, 'mensagem': resultado['mensagem']})
        
        return jsonify({'sucesso': True, 'mensagem': f'✅ {len(resultados)} venda(s) registrada(s) com sucesso!'})
    
    print("✅ Módulo de Vendas Rápidas carregado!")
    print("   📍 Acesse: /vendas/rapido")
