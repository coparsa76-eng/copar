# -*- coding: utf-8 -*-
"""
MÓDULO DE VENDAS - Funcionalidades separadas do sistema principal
"""

from flask import render_template_string, jsonify, request, session
import psycopg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Conexão com banco (usa a mesma string do app original)
DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return None

def verificar_acesso_vendas():
    """Verifica se usuário tem acesso à área de vendas"""
    if 'produtor_id' not in session:
        return False
    # Quem pode acessar: gerente, superadmin, ou algum outro que você definir
    tipo = session.get('tipo')
    return tipo in ('gerente', 'superadmin')

# ============================================
# FUNÇÕES DE NEGÓCIO DA ÁREA DE VENDAS
# ============================================

def buscar_produtores_para_venda():
    """Busca todos os produtores com estoque disponível"""
    conn = conectar_banco()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT p.id, p.nome, p.matricula
            FROM produtores p
            JOIN estoque e ON p.id = e.produtor_id
            WHERE e.peso > 0
            ORDER BY p.nome
        """)
        result = [{'id': r[0], 'nome': r[1], 'matricula': r[2]} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar produtores: {e}")
        return []

def buscar_estoque_produtor_para_venda(produtor_id):
    """Busca estoque disponível de um produtor para venda"""
    conn = conectar_banco()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.tipo_alho, e.classe, e.local_estoque, 
                   SUM(e.peso) as peso_total,
                   SUM(e.horas_banca) as horas_banca
            FROM estoque e
            WHERE e.produtor_id = %s AND e.peso > 0
            GROUP BY e.id, e.tipo_alho, e.classe, e.local_estoque
            HAVING SUM(e.peso) > 0
            ORDER BY e.tipo_alho, e.classe
        """, (produtor_id,))
        
        result = []
        for r in cur.fetchall():
            result.append({
                'id': r[0],
                'tipo': r[1] or 'Não definido',
                'classe': r[2] or 'Não classificada',
                'local': r[3],
                'peso_disponivel': float(r[4]),
                'horas_banca': float(r[5] or 0)
            })
        
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque: {e}")
        return []

def calcular_valor_venda(tipo_alho, classe, peso, preco_por_kg):
    """Calcula o valor total da venda"""
    return peso * preco_por_kg

def registrar_venda(produtor_id, itens_venda, valor_total, valor_produtor, percentual_comissao):
    """Registra uma nova venda no sistema"""
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    
    try:
        cur = conn.cursor()
        
        # Registrar a venda
        cur.execute("""
            INSERT INTO vendas (produtor_id, tipo_alho, classe, peso, valor_total, valor_produtor, status_pagamento)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (
            produtor_id,
            itens_venda[0]['tipo'],  # Simplificado - você pode melhorar
            itens_venda[0]['classe'],
            sum(item['peso'] for item in itens_venda),
            valor_total,
            valor_produtor,
            'Pendente'
        ))
        
        venda_id = cur.fetchone()[0]
        
        # Inserir créditos do produtor
        cur.execute("""
            INSERT INTO creditos_produtor (venda_id, saldo)
            VALUES (%s, %s)
        """, (venda_id, valor_produtor))
        
        # Remover os itens do estoque (dar baixa)
        for item in itens_venda:
            cur.execute("""
                UPDATE estoque 
                SET peso = peso - %s 
                WHERE id = %s AND peso >= %s
            """, (item['peso'], item['estoque_id'], item['peso']))
            
            if cur.rowcount == 0:
                raise Exception(f"Erro ao dar baixa no estoque do item {item['tipo']}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            'sucesso': True,
            'mensagem': f'Venda registrada com sucesso! ID: {venda_id}',
            'venda_id': venda_id
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro ao registrar venda: {e}")
        return {'sucesso': False, 'mensagem': f'Erro: {str(e)}'}

# ============================================
# HTML DA NOVA ÁREA DE VENDAS
# ============================================

HTML_VENDAS = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COPAR - Nova Venda</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'DM Sans', sans-serif;
            background: #f2f5f0;
            color: #1a2e19;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: #2a5c28;
            color: white;
            padding: 20px;
            border-radius: 14px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            border-radius: 14px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .card h2 {
            color: #2a5c28;
            margin-bottom: 15px;
            font-size: 1.2rem;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            font-size: 0.85rem;
            color: #6b7c6a;
        }
        select, input {
            width: 100%;
            padding: 10px;
            border: 1.5px solid #dde8db;
            border-radius: 10px;
            font-family: inherit;
            font-size: 0.9rem;
        }
        button {
            background: #2a5c28;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
        }
        button:hover {
            background: #3d7a3a;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #dde8db;
        }
        th {
            background: #f4f9f3;
            color: #2a5c28;
            font-weight: 600;
        }
        .btn-remover {
            background: #c0392b;
            padding: 5px 10px;
            font-size: 0.8rem;
        }
        .total-area {
            background: #f4f9f3;
            padding: 15px;
            border-radius: 10px;
            margin-top: 15px;
        }
        .alert {
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 15px;
        }
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .btn-voltar {
            background: #6b7c6a;
            margin-right: 10px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>💰 Nova Venda</h1>
        <p>Registre vendas de produtos dos produtores</p>
    </div>
    
    <div id="mensagem"></div>
    
    <div class="card">
        <h2>1. Selecione o Produtor</h2>
        <div class="form-group">
            <label>Produtor:</label>
            <select id="produtor_id" onchange="carregarEstoque()">
                <option value="">-- Selecione --</option>
                {% for p in produtores %}
                <option value="{{ p.id }}">{{ p.nome }} ({{ p.matricula }})</option>
                {% endfor %}
            </select>
        </div>
    </div>
    
    <div class="card" id="card_estoque" style="display:none;">
        <h2>2. Itens Disponíveis para Venda</h2>
        <div id="estoque_lista"></div>
    </div>
    
    <div class="card" id="card_carrinho" style="display:none;">
        <h2>3. Carrinho de Venda</h2>
        <table id="tabela_carrinho">
            <thead>
                <tr><th>Produto</th><th>Classe</th><th>Origem</th><th>Peso (kg)</th><th>Valor Unit.</th><th>Subtotal</th><th>Ação</th></tr>
            </thead>
            <tbody id="carrinho_corpo"></tbody>
        </table>
        <div class="total-area">
            <strong>Total da Venda: </strong> <span id="total_venda">R$ 0,00</span><br>
            <strong>Comissão (10%): </strong> <span id="comissao">R$ 0,00</span><br>
            <strong>Valor para o Produtor: </strong> <span id="valor_produtor">R$ 0,00</span>
        </div>
        <button onclick="finalizarVenda()">✅ Finalizar Venda</button>
        <button onclick="limparCarrinho()" style="background:#c0392b;">🗑️ Limpar Carrinho</button>
    </div>
    
    <div style="margin-top: 20px;">
        <button class="btn-voltar" onclick="window.location.href='/gerente'">← Voltar ao Painel</button>
    </div>
</div>

<script>
let carrinho = [];
let precosBase = {
    'Roxo': 8.50,
    'Branco': 7.90,
    'Chinês': 6.50,
    'Roxo Cati': 9.00
};

function carregarEstoque() {
    const produtorId = document.getElementById('produtor_id').value;
    if (!produtorId) return;
    
    fetch('/api/vendas/estoque-produtor', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({produtor_id: produtorId})
    })
    .then(res => res.json())
    .then(data => {
        if (data.sucesso) {
            exibirEstoque(data.estoque);
            document.getElementById('card_estoque').style.display = 'block';
        } else {
            mostrarMensagem(data.mensagem, 'error');
        }
    });
}

function exibirEstoque(estoque) {
    const div = document.getElementById('estoque_lista');
    if (!estoque.length) {
        div.innerHTML = '<p>Nenhum estoque disponível para este produtor.</p>';
        return;
    }
    
    let html = '<table><thead><tr><th>Tipo</th><th>Classe</th><th>Local</th><th>Peso (kg)</th><th>Preço/kg</th><th>Ação</th></tr></thead><tbody>';
    estoque.forEach(item => {
        const preco = precosBase[item.tipo] || 7.00;
        html += `<tr>
            <td>${item.tipo}</td>
            <td>${item.classe}</td>
            <td>${item.local}</td>
            <td>${item.peso_disponivel.toFixed(2)} kg</td>
            <td>R$ ${preco.toFixed(2)}</td>
            <td><button onclick="adicionarAoCarrinho(${item.id}, '${item.tipo}', '${item.classe}', ${item.peso_disponivel}, ${preco})">➕ Adicionar</button></td>
        </tr>`;
    });
    html += '</tbody></table>';
    div.innerHTML = html;
}

function adicionarAoCarrinho(estoqueId, tipo, classe, pesoMax, preco) {
    let peso = prompt(`Quantos kg de ${tipo} - ${classe}? (Máximo: ${pesoMax.toFixed(2)} kg)`, "1.0");
    if (!peso) return;
    
    peso = parseFloat(peso);
    if (isNaN(peso) || peso <= 0) {
        alert("Peso inválido!");
        return;
    }
    if (peso > pesoMax) {
        alert(`Peso máximo é ${pesoMax.toFixed(2)} kg!`);
        return;
    }
    
    const subtotal = peso * preco;
    carrinho.push({
        estoque_id: estoqueId,
        tipo: tipo,
        classe: classe,
        peso: peso,
        preco_unitario: preco,
        subtotal: subtotal
    });
    
    atualizarCarrinho();
    mostrarMensagem(`✅ ${peso} kg de ${tipo} adicionado ao carrinho`, 'success');
}

function atualizarCarrinho() {
    const tbody = document.getElementById('carrinho_corpo');
    const totalSpan = document.getElementById('total_venda');
    const comissaoSpan = document.getElementById('comissao');
    const valorProdutorSpan = document.getElementById('valor_produtor');
    
    if (carrinho.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Carrinho vazio</td></tr>';
        totalSpan.innerText = 'R$ 0,00';
        comissaoSpan.innerText = 'R$ 0,00';
        valorProdutorSpan.innerText = 'R$ 0,00';
        document.getElementById('card_carrinho').style.display = 'none';
        return;
    }
    
    let html = '';
    let total = 0;
    carrinho.forEach((item, idx) => {
        total += item.subtotal;
        html += `<tr>
            <td>${item.tipo}</td>
            <td>${item.classe}</td>
            <td>${item.peso.toFixed(2)} kg</td>
            <td>R$ ${item.preco_unitario.toFixed(2)}</td>
            <td>R$ ${item.subtotal.toFixed(2)}</td>
            <td><button class="btn-remover" onclick="removerDoCarrinho(${idx})">Remover</button></td>
        </tr>`;
    });
    
    tbody.innerHTML = html;
    const comissao = total * 0.10;
    const valorProdutor = total - comissao;
    
    totalSpan.innerText = `R$ ${total.toFixed(2)}`;
    comissaoSpan.innerText = `R$ ${comissao.toFixed(2)}`;
    valorProdutorSpan.innerText = `R$ ${valorProdutor.toFixed(2)}`;
    
    document.getElementById('card_carrinho').style.display = 'block';
}

function removerDoCarrinho(idx) {
    carrinho.splice(idx, 1);
    atualizarCarrinho();
    mostrarMensagem('Item removido do carrinho', 'success');
}

function limparCarrinho() {
    if (confirm('Limpar todo o carrinho?')) {
        carrinho = [];
        atualizarCarrinho();
        mostrarMensagem('Carrinho limpo', 'success');
    }
}

function finalizarVenda() {
    if (carrinho.length === 0) {
        alert('Carrinho vazio!');
        return;
    }
    
    const produtorId = document.getElementById('produtor_id').value;
    const total = carrinho.reduce((sum, item) => sum + item.subtotal, 0);
    const comissao = total * 0.10;
    const valorProdutor = total - comissao;
    
    if (!confirm(`Confirmar venda no valor de R$ ${total.toFixed(2)}?\nValor para o produtor: R$ ${valorProdutor.toFixed(2)}`)) {
        return;
    }
    
    fetch('/api/vendas/registrar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            produtor_id: parseInt(produtorId),
            itens: carrinho,
            valor_total: total,
            valor_produtor: valorProdutor,
            comissao: comissao
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.sucesso) {
            mostrarMensagem(data.mensagem, 'success');
            carrinho = [];
            atualizarCarrinho();
            document.getElementById('produtor_id').value = '';
            document.getElementById('card_estoque').style.display = 'none';
            setTimeout(() => location.reload(), 2000);
        } else {
            mostrarMensagem(data.mensagem, 'error');
        }
    });
}

function mostrarMensagem(msg, tipo) {
    const div = document.getElementById('mensagem');
    div.innerHTML = `<div class="alert alert-${tipo}">${msg}</div>`;
    setTimeout(() => div.innerHTML = '', 5000);
}
</script>
</body>
</html>
"""

# ============================================
# ROTAS DO MÓDULO DE VENDAS
# ============================================

def registrar_rotas_vendas(app):
    """Registra todas as rotas do módulo de vendas"""
    
    @app.route('/vendas/nova')
    def nova_venda():
        """Página principal da nova área de vendas"""
        if not verificar_acesso_vendas():
            return "Acesso negado. Área restrita ao gerente.", 403
        
        produtores = buscar_produtores_para_venda()
        return render_template_string(HTML_VENDAS, produtores=produtores)
    
    @app.route('/api/vendas/estoque-produtor', methods=['POST'])
    def api_vendas_estoque_produtor():
        """API para buscar estoque de um produtor"""
        if not verificar_acesso_vendas():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        produtor_id = data.get('produtor_id')
        
        if not produtor_id:
            return jsonify({'sucesso': False, 'mensagem': 'Produtor não informado'})
        
        estoque = buscar_estoque_produtor_para_venda(produtor_id)
        return jsonify({'sucesso': True, 'estoque': estoque})
    
    @app.route('/api/vendas/registrar', methods=['POST'])
    def api_vendas_registrar():
        """API para registrar uma nova venda"""
        if not verificar_acesso_vendas():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        
        resultado = registrar_venda(
            data.get('produtor_id'),
            data.get('itens', []),
            data.get('valor_total', 0),
            data.get('valor_produtor', 0),
            10  # 10% de comissão
        )
        
        return jsonify(resultado)
    
    print("✅ Rotas de vendas registradas:")
    print("   - /vendas/nova (página principal)")
    print("   - /api/vendas/estoque-produtor (API)")
    print("   - /api/vendas/registrar (API)")
