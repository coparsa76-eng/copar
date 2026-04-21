# -*- coding: utf-8 -*-
from flask import render_template_string, jsonify, request, session
import psycopg
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

TIPOS_ALHO = ['Ito', 'Chonan', 'São Valentim']
CLASSES = ['Indústria', 'Classe 2', 'Classe 3', 'Classe 4', 'Classe 5', 'Classe 6', 'Classe 7']
TIPOS_ESTOQUE = ['Classificação', 'Banca', 'Toletagem']

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro conexão: {e}")
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
            SELECT p.id, p.nome, p.matricula, COALESCE(SUM(e.peso), 0)
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.tipo_alho = %s AND e.classe = %s AND e.local_estoque = %s AND e.peso > 0
            GROUP BY p.id, p.nome, p.matricula
            HAVING COALESCE(SUM(e.peso), 0) > 0
            ORDER BY p.nome
        """, (tipo_alho, classe, local_estoque))
        result = [{'id': r[0], 'nome': r[1], 'matricula': r[2], 'peso_disponivel': float(r[3])} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro: {e}")
        return []

def registrar_venda(produtor_id, tipo_alho, classe, local_origem, peso, valor_kg):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE produtor_id=%s AND tipo_alho=%s AND classe=%s AND local_estoque=%s AND peso>0",
                    (produtor_id, tipo_alho, classe, local_origem))
        disp = float(cur.fetchone()[0])
        if disp < peso:
            raise ValueError(f"Estoque insuficiente! Disponível: {disp:.2f} Kg")
        
        valor_total = peso * valor_kg
        comissao = valor_total * 0.10
        valor_produtor = valor_total - comissao
        
        cur.execute("""
            INSERT INTO vendas (produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor, desconto_comissao, comprador, origem_estoque, status_pagamento)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (produtor_id, tipo_alho, classe, peso, valor_kg, valor_total, valor_produtor, comissao, 'Venda Rápida', local_origem, 'Pendente'))
        venda_id = cur.fetchone()[0]
        
        cur.execute("INSERT INTO creditos_produtor (produtor_id, venda_id, valor_credito, saldo) VALUES (%s,%s,%s,%s)",
                    (produtor_id, venda_id, valor_produtor, valor_produtor))
        
        cur.execute("SELECT id, peso FROM estoque WHERE produtor_id=%s AND tipo_alho=%s AND classe=%s AND local_estoque=%s AND peso>0 ORDER BY data_registro FOR UPDATE",
                    (produtor_id, tipo_alho, classe, local_origem))
        rows = cur.fetchall()
        restante = peso
        for eid, epeso in rows:
            if restante <= 0: break
            epeso = float(epeso)
            if restante >= epeso - 0.001:
                cur.execute("DELETE FROM estoque WHERE id=%s", (eid,))
                restante -= epeso
            else:
                cur.execute("UPDATE estoque SET peso=%s WHERE id=%s", (round(epeso - restante, 4), eid))
                restante = 0
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {'sucesso': True, 'mensagem': f'✅ Venda #{venda_id} registrada!', 'venda_id': venda_id}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {'sucesso': False, 'mensagem': f'❌ Erro: {str(e)}'}

# HTML SIMPLES PARA TESTE
HTML_SIMPLES = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Vendas Rápidas</title>
    <style>
        body { font-family: Arial; padding: 20px; background: #f0f0f0; }
        .card { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        select, input, button { width: 100%; padding: 10px; margin: 5px 0; }
        button { background: green; color: white; border: none; cursor: pointer; }
        .btn-danger { background: red; }
        .carrinho-item { border: 1px solid #ddd; padding: 10px; margin: 10px 0; }
    </style>
</head>
<body>
<div style="max-width:600px; margin:auto">
    <div class="card">
        <h2>⚡ Vendas Rápidas</h2>
        <select id="tipo"><option value="">Tipo</option>{% for t in tipos_alho %}<option>{{ t }}</option>{% endfor %}</select>
        <select id="classe"><option value="">Classe</option>{% for c in classes %}<option>{{ c }}</option>{% endfor %}</select>
        <select id="local"><option value="">Local</option>{% for l in locais %}<option>{{ l }}</option>{% endfor %}</select>
        <input type="number" id="preco" placeholder="Preço por KG">
        <button id="buscarProdutos">🔍 Buscar Produtores</button>
    </div>
    
    <div class="card" id="cardProdutores" style="display:none">
        <h2>Produtores</h2>
        <div id="listaProdutores"></div>
        <button id="addLinha">➕ Adicionar Produtor</button>
    </div>
    
    <div class="card" id="cardCarrinho" style="display:none">
        <h2>Carrinho</h2>
        <div id="carrinho"></div>
        <div style="background:#e0e0e0; padding:10px; margin:10px 0">
            <strong>Total: R$ <span id="total">0.00</span></strong>
        </div>
        <button id="finalizar" style="background:green">✅ FINALIZAR</button>
        <button id="limpar" style="background:red">🗑️ LIMPAR</button>
    </div>
    
    <button onclick="location.href='/gerente'">← Voltar</button>
</div>

<script>
let carrinho = [];
let produtoresLista = [];
let nextId = 0;

function mostrarAlerta(msg, cor) {
    alert(msg);
}

document.getElementById('buscarProdutos').onclick = async () => {
    const tipo = document.getElementById('tipo').value;
    const cls = document.getElementById('classe').value;
    const local = document.getElementById('local').value;
    const preco = document.getElementById('preco').value;
    if (!tipo || !cls || !local || !preco) {
        alert('Preencha todos os campos!');
        return;
    }
    const res = await fetch('/api/vendas-rapido/produtores', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tipo_alho: tipo, classe: cls, local_estoque: local})
    });
    const data = await res.json();
    if (data.sucesso) {
        produtoresLista = data.produtores;
        document.getElementById('cardProdutores').style.display = 'block';
        if (produtoresLista.length === 0) alert('Nenhum produtor com estoque!');
    }
};

document.getElementById('addLinha').onclick = () => {
    if (produtoresLista.length === 0) {
        alert('Busque produtores primeiro!');
        return;
    }
    carrinho.push({id: nextId++, produtor_id: null, nome: '', matricula: '', peso: 0, peso_disponivel: 0, preco: parseFloat(document.getElementById('preco').value)});
    renderizarCarrinho();
};

function removerLinha(id) {
    carrinho = carrinho.filter(i => i.id !== id);
    renderizarCarrinho();
}

function selecionarProdutor(idx, produtorId, nome, matricula, pesoDisponivel) {
    carrinho[idx].produtor_id = produtorId;
    carrinho[idx].nome = nome;
    carrinho[idx].matricula = matricula;
    carrinho[idx].peso_disponivel = pesoDisponivel;
    renderizarCarrinho();
}

function atualizarPeso(idx, peso) {
    carrinho[idx].peso = parseFloat(peso) || 0;
    if (carrinho[idx].peso > carrinho[idx].peso_disponivel) {
        alert(`Peso excede disponível (${carrinho[idx].peso_disponivel} kg)`);
        carrinho[idx].peso = carrinho[idx].peso_disponivel;
    }
    renderizarCarrinho();
}

function renderizarCarrinho() {
    const container = document.getElementById('listaProdutores');
    const carrinhoDiv = document.getElementById('carrinho');
    let total = 0;
    
    let html = '';
    carrinho.forEach((item, idx) => {
        const subtotal = item.peso * item.preco;
        total += subtotal;
        html += `
            <div class="carrinho-item">
                <strong>Produtor ${idx+1}</strong>
                <select id="sel_${idx}" onchange="selecionarProdutor(${idx}, this.value, this.options[this.selectedIndex].text.split('|')[0], this.value.split('|')[1] || '', parseFloat(this.options[this.selectedIndex].getAttribute('data-peso')))">
                    <option value="">Selecione...</option>
                    ${produtoresLista.map(p => `<option value="${p.id}|${p.matricula}" data-peso="${p.peso_disponivel}" ${item.produtor_id === p.id ? 'selected' : ''}>${p.nome} | ${p.matricula} | ${p.peso_disponivel} kg</option>`).join('')}
                </select>
                <input type="number" step="0.001" placeholder="Peso (kg)" value="${item.peso || ''}" onchange="atualizarPeso(${idx}, this.value)">
                <input type="text" readonly value="R$ ${subtotal.toFixed(2)}" style="background:#f0f0f0">
                <button onclick="removerLinha(${item.id})" style="background:red; margin-top:5px">Remover</button>
            </div>
        `;
    });
    container.innerHTML = html + (carrinho.length === 0 ? '<p>Nenhum produtor adicionado</p>' : '');
    
    document.getElementById('total').innerText = total.toFixed(2);
    document.getElementById('cardCarrinho').style.display = carrinho.length > 0 ? 'block' : 'none';
}

document.getElementById('finalizar').onclick = async () => {
    const itensValidos = carrinho.filter(i => i.produtor_id && i.peso > 0);
    if (itensValidos.length === 0) {
        alert('Adicione pelo menos um produtor com peso!');
        return;
    }
    const total = itensValidos.reduce((s,i) => s + (i.peso * i.preco), 0);
    if (!confirm(`Confirmar venda de R$ ${total.toFixed(2)}?`)) return;
    
    const tipo = document.getElementById('tipo').value;
    const cls = document.getElementById('classe').value;
    const local = document.getElementById('local').value;
    
    const res = await fetch('/api/vendas-rapido/finalizar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            itens: itensValidos.map(i => ({
                produtor_id: i.produtor_id,
                tipo_alho: tipo,
                classe: cls,
                local_origem: local,
                peso: i.peso,
                valor_kg: i.preco
            }))
        })
    });
    const data = await res.json();
    alert(data.mensagem);
    if (data.sucesso) location.reload();
};

document.getElementById('limpar').onclick = () => {
    if (confirm('Limpar tudo?')) {
        carrinho = [];
        nextId = 0;
        renderizarCarrinho();
    }
};
</script>
</body>
</html>
"""

def registrar_rotas_vendas_rapido(app):
    @app.route('/vendas/rapido')
    def vendas_rapido():
        if not verificar_acesso():
            return "Acesso negado", 403
        return render_template_string(HTML_SIMPLES, tipos_alho=TIPOS_ALHO, classes=CLASSES, locais=TIPOS_ESTOQUE)
    
    @app.route('/api/vendas-rapido/produtores', methods=['POST'])
    def api_produtores():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        data = request.get_json()
        produtores = buscar_estoque_disponivel(data.get('tipo_alho'), data.get('classe'), data.get('local_estoque'))
        return jsonify({'sucesso': True, 'produtores': produtores})
    
    @app.route('/api/vendas-rapido/finalizar', methods=['POST'])
    def api_finalizar():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        data = request.get_json()
        for item in data.get('itens', []):
            result = registrar_venda(item['produtor_id'], item['tipo_alho'], item['classe'], item['local_origem'], item['peso'], item['valor_kg'])
            if not result['sucesso']:
                return jsonify(result)
        return jsonify({'sucesso': True, 'mensagem': '✅ Vendas registradas com sucesso!'})
    
    print("✅ Módulo Vendas Rápidas carregado! Acesse: /vendas/rapido")
