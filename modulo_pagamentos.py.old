# -*- coding: utf-8 -*-
"""
MÓDULO DE PAGAMENTOS - Gestão de pagamentos aos produtores
"""

from flask import render_template_string, jsonify, request, session
import psycopg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

FORMAS_PAGAMENTO = ['Dinheiro', 'PIX', 'Transferência', 'Cheque', 'Adiantamento']

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

def buscar_produtor_por_matricula(matricula):
    """Busca produtor pela matrícula"""
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, matricula, COALESCE(cpf, '') as cpf
            FROM produtores 
            WHERE matricula = %s
        """, (matricula.strip(),))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {'id': row[0], 'nome': row[1], 'matricula': row[2], 'cpf': row[3]}
        return None
    except Exception as e:
        logger.error(f"Erro buscar_produtor: {e}")
        return None

def buscar_vendas_pendentes(produtor_id):
    """Busca todas as vendas pendentes de pagamento de um produtor"""
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso, 
                   v.valor_total, v.valor_produtor, v.status_pagamento,
                   COALESCE(cp.saldo, v.valor_produtor) as saldo
            FROM vendas v
            LEFT JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s AND v.status_pagamento != 'Pago'
            ORDER BY v.data_venda ASC
        """, (produtor_id,))
        
        vendas = []
        for row in cur.fetchall():
            vendas.append({
                'id': row[0],
                'data': row[1].strftime("%d/%m/%Y") if row[1] else "",
                'tipo': row[2],
                'classe': row[3],
                'peso': float(row[4]),
                'valor_total': float(row[5]),
                'valor_produtor': float(row[6]),
                'status': row[7],
                'saldo': float(row[8])
            })
        cur.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro buscar_vendas_pendentes: {e}")
        return []

def buscar_adiantamentos(produtor_id):
    """Busca adiantamentos já realizados (pagamentos sem venda vinculada)"""
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, data_pagamento, valor_total, forma_pagamento, observacoes
            FROM pagamentos
            WHERE produtor_id = %s AND (observacoes ILIKE '%adiantamento%' OR observacoes ILIKE '%Adiantamento%')
            ORDER BY data_pagamento DESC
        """, (produtor_id,))
        
        adiantamentos = []
        for row in cur.fetchall():
            adiantamentos.append({
                'id': row[0],
                'data': row[1].strftime("%d/%m/%Y") if row[1] else "",
                'valor': float(row[2]),
                'forma': row[3],
                'obs': row[4] or ""
            })
        cur.close()
        conn.close()
        return adiantamentos
    except Exception as e:
        logger.error(f"Erro buscar_adiantamentos: {e}")
        return []

def registrar_pagamento(produtor_id, vendas_ids, valor_pago, forma_pagamento, observacao):
    """Registra pagamento para vendas específicas"""
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    
    try:
        cur = conn.cursor()
        
        # Calcular valor total das vendas selecionadas
        placeholders = ','.join(['%s'] * len(vendas_ids))
        cur.execute(f"""
            SELECT SUM(valor_produtor) FROM vendas 
            WHERE id IN ({placeholders}) AND status_pagamento != 'Pago'
        """, vendas_ids)
        total_disponivel = float(cur.fetchone()[0] or 0)
        
        if valor_pago > total_disponivel + 0.01:
            raise ValueError(f"Valor excede o total disponível (R$ {total_disponivel:.2f})")
        
        # Registrar pagamento principal
        cur.execute("""
    INSERT INTO pagamentos (produtor_id, valor_total, forma_pagamento, observacoes, data_pagamento)
    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING id
""", (produtor_id, valor_pago, forma_pagamento, observacao))
        pagamento_id = cur.fetchone()[0]
        
        # Distribuir pagamento entre as vendas (FIFO)
        restante = valor_pago
        for venda_id in vendas_ids:
            if restante <= 0:
                break
            
            # Buscar saldo atual da venda
            cur.execute("""
                SELECT saldo FROM creditos_produtor WHERE venda_id = %s
            """, (venda_id,))
            row = cur.fetchone()
            if not row:
                continue
            
            saldo_atual = float(row[0])
            if saldo_atual <= 0:
                continue
            
            valor_pagar = min(restante, saldo_atual)
            
            # Registrar item pago
            cur.execute("""
                INSERT INTO itens_pagos (pagamento_id, credito_id, valor_pago)
                SELECT %s, cp.id, %s
                FROM creditos_produtor cp
                WHERE cp.venda_id = %s
            """, (pagamento_id, valor_pagar, venda_id))
            
            # Atualizar crédito do produtor
            cur.execute("""
                UPDATE creditos_produtor 
                SET valor_pago = valor_pago + %s, saldo = saldo - %s
                WHERE venda_id = %s
            """, (valor_pagar, valor_pagar, venda_id))
            
            # Verificar se venda foi totalmente paga
            cur.execute("SELECT saldo FROM creditos_produtor WHERE venda_id = %s", (venda_id,))
            novo_saldo = float(cur.fetchone()[0])
            
            if novo_saldo <= 0.01:
                cur.execute("UPDATE vendas SET status_pagamento = 'Pago' WHERE id = %s", (venda_id,))
            else:
                cur.execute("UPDATE vendas SET status_pagamento = 'Parcial' WHERE id = %s", (venda_id,))
            
            restante -= valor_pagar
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Buscar nome do produtor
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
            'mensagem': f'✅ Pagamento #{pagamento_id} registrado!\nProdutor: {nome_produtor}\nValor: R$ {valor_pago:.2f}',
            'pagamento_id': pagamento_id
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return {'sucesso': False, 'mensagem': str(e)}

def registrar_adiantamento(produtor_id, valor, forma_pagamento, observacao):
    """Registra um adiantamento (pagamento sem venda vinculada)"""
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    
    try:
        cur = conn.cursor()
        
        # Registrar como pagamento com observação especial
        obs = f"Adiantamento - {observacao}" if observacao else "Adiantamento"
        cur.execute("""
            INSERT INTO pagamentos (produtor_id, valor_total, forma_pagamento, observacoes)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (produtor_id, valor, forma_pagamento, obs))
        pagamento_id = cur.fetchone()[0]
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            'sucesso': True,
            'mensagem': f'✅ Adiantamento #{pagamento_id} registrado!\nValor: R$ {valor:.2f}',
            'pagamento_id': pagamento_id
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return {'sucesso': False, 'mensagem': str(e)}

def gerar_recibo(produtor_id, pagamento_id):
    """Gera dados para o recibo"""
    conn = conectar_banco()
    if not conn:
        return None
    
    try:
        cur = conn.cursor()
        
        # Dados do produtor
        cur.execute("SELECT nome, matricula, cpf FROM produtores WHERE id = %s", (produtor_id,))
        produtor = cur.fetchone()
        
        # Dados do pagamento
        cur.execute("""
            SELECT data_pagamento, valor_total, forma_pagamento, observacoes
            FROM pagamentos WHERE id = %s
        """, (pagamento_id,))
        pagamento = cur.fetchone()
        
        # Vendas pagas neste pagamento
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso, 
                   v.valor_total, ip.valor_pago
            FROM itens_pagos ip
            JOIN creditos_produtor cp ON ip.credito_id = cp.id
            JOIN vendas v ON cp.venda_id = v.id
            WHERE ip.pagamento_id = %s
        """, (pagamento_id,))
        vendas = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return {
            'produtor': {'nome': produtor[0], 'matricula': produtor[1], 'cpf': produtor[2] if produtor[2] else '---'},
            'pagamento': {
                'id': pagamento_id,
                'data': pagamento[0].strftime("%d/%m/%Y %H:%M") if pagamento[0] else "",
                'valor': float(pagamento[1]),
                'forma': pagamento[2],
                'obs': pagamento[3] or ""
            },
            'vendas': [{'id': v[0], 'data': v[1].strftime("%d/%m/%Y"), 'tipo': v[2], 
                       'classe': v[3], 'peso': float(v[4]), 'total': float(v[5]), 
                       'pago': float(v[6])} for v in vendas]
        }
    except Exception as e:
        logger.error(f"Erro gerar_recibo: {e}")
        return None


# ============================================
# HTML DA TELA DE PAGAMENTOS
# ============================================

HTML_PAGAMENTOS = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Pagamentos – COPAR</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --verde:#1a5c2a;--verde2:#2d7a3f;--verde-pale:#eef6f0;--verde-light:#d4edda;
  --amber:#b45309;--amber-pale:#fef3c7;
  --red:#c0392b;--red-pale:#fde8e8;
  --blue:#1e4a8c;--blue-pale:#e8eef8;
  --text:#111827;--muted:#6b7280;--border:#d1d5db;
  --white:#fff;--bg:#f3f4f6;
  --radius:10px;--mono:'IBM Plex Mono',monospace;
  --shadow:0 2px 12px rgba(0,0,0,.08);
}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100dvh}
nav{background:var(--verde);padding:.75rem 1.25rem;display:flex;align-items:center;
    justify-content:space-between;position:sticky;top:0;z-index:100;gap:.75rem}
.nav-brand{color:#fff;font-weight:700;font-size:1.1rem;display:flex;align-items:center;gap:.5rem}
.nav-back{color:rgba(255,255,255,.85);text-decoration:none;font-size:.82rem;border:1px solid rgba(255,255,255,.3);
          padding:.4rem .9rem;border-radius:8px;transition:all .2s}
.nav-back:hover{background:rgba(255,255,255,.15)}
.wrap{max-width:1200px;margin:0 auto;padding:1.25rem}

.card{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:1rem;overflow:hidden}
.card-header{background:var(--verde);color:#fff;padding:.75rem 1.1rem;font-weight:700;font-size:.9rem}
.card-body{padding:1.25rem}

.busca-produtor{display:flex;gap:.75rem;align-items:flex-end}
.busca-produtor input{flex:1;padding:.7rem;border:1.5px solid var(--border);border-radius:8px;font-size:.9rem}
.busca-produtor button{padding:.7rem 1.5rem;background:var(--verde);color:#fff;border:none;border-radius:8px;
                       font-weight:600;cursor:pointer;white-space:nowrap}
.busca-produtor button:hover{background:var(--verde2)}

.produtor-info{background:var(--verde-pale);border-radius:8px;padding:1rem;margin-top:1rem;display:none}
.produtor-info.show{display:block}
.produtor-info .nome{font-size:1.1rem;font-weight:700;color:var(--verde)}
.produtor-info .saldo{font-family:var(--mono);font-size:1.3rem;font-weight:700;color:var(--verde)}

.vendas-lista{max-height:400px;overflow-y:auto}
.venda-item{display:flex;align-items:center;padding:.75rem;border-bottom:1px solid var(--border);cursor:pointer;transition:background .2s}
.venda-item:hover{background:var(--verde-pale)}
.venda-item.selecionado{background:var(--verde-light);border-left:3px solid var(--verde)}
.venda-check{margin-right:1rem}
.venda-info{flex:1;display:grid;grid-template-columns:100px 120px 1fr 120px 120px;gap:.5rem;align-items:center}
@media(max-width:700px){.venda-info{grid-template-columns:1fr;gap:.25rem}}
.venda-data{font-size:.8rem;color:var(--muted)}
.venda-produto{font-weight:600}
.venda-valor{font-family:var(--mono);font-weight:600}
.venda-status{font-size:.7rem;padding:.15rem .5rem;border-radius:999px;display:inline-block}
.status-pendente{background:var(--amber-pale);color:var(--amber)}
.status-parcial{background:var(--blue-pale);color:var(--blue)}

.resumo-pagamento{background:var(--bg);border-radius:8px;padding:1rem;margin-top:1rem}
.resumo-linha{display:flex;justify-content:space-between;margin-bottom:.5rem}
.valor-destaque{font-size:1.5rem;font-weight:700;color:var(--verde);font-family:var(--mono)}

.form-pagamento{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem}
@media(max-width:600px){.form-pagamento{grid-template-columns:1fr}}
.form-group label{font-size:.7rem;font-weight:700;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:.25rem}
.form-group input,.form-group select{width:100%;padding:.6rem;border:1.5px solid var(--border);border-radius:8px;font-size:.9rem}
.btn-pagar{background:var(--verde);color:#fff;border:none;padding:.9rem;border-radius:8px;
           font-weight:700;font-size:1rem;cursor:pointer;margin-top:1rem}
.btn-pagar:hover{background:var(--verde2)}
.btn-pagar:disabled{opacity:.5;cursor:not-allowed}

.adiantamento-area{margin-top:1.5rem;padding-top:1rem;border-top:2px dashed var(--border)}
.btn-adiantar{background:var(--amber);color:#fff;border:none;padding:.8rem;border-radius:8px;
              font-weight:600;cursor:pointer;width:100%}
.btn-adiantar:hover{background:#b45309}

.toast{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%) translateY(100px);
       background:#111;color:#fff;padding:.75rem 1.5rem;border-radius:999px;font-size:.88rem;
       font-weight:600;z-index:999;transition:transform .3s}
.toast.show{transform:translateX(-50%) translateY(0)}
.toast.ok{background:var(--verde)}
.toast.err{background:var(--red)}

.spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);
      border-top-color:#fff;border-radius:50%;animation:sp .6s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}

.modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center}
.modal-content{background:#fff;border-radius:12px;max-width:500px;width:90%;max-height:80vh;overflow:auto}
.modal-header{padding:1rem;border-bottom:1px solid var(--border);font-weight:700}
.modal-body{padding:1rem}
.modal-footer{padding:1rem;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:.5rem}
.btn-modal{background:var(--verde);color:#fff;border:none;padding:.5rem 1rem;border-radius:6px;cursor:pointer}
.recibo-linha{display:flex;justify-content:space-between;margin-bottom:.5rem;font-size:.85rem}
</style>
</head>
<body>
<nav>
  <div class="nav-brand">💰 COPAR — Pagamentos</div>
  <a href="/gerente" class="nav-back">← Gerencial</a>
</nav>

<div class="wrap">
  <!-- Busca Produtor -->
  <div class="card">
    <div class="card-header">🔍 Buscar Produtor</div>
    <div class="card-body">
      <div class="busca-produtor">
        <input type="text" id="matricula" placeholder="Digite a matrícula do produtor..." autocomplete="off">
        <button id="btnBuscar">Buscar</button>
      </div>
      <div id="produtorInfo" class="produtor-info"></div>
    </div>
  </div>

  <!-- Vendas Pendentes -->
  <div class="card" id="cardVendas" style="display:none">
    <div class="card-header">📋 Vendas Pendentes</div>
    <div class="card-body">
      <div class="vendas-lista" id="vendasLista"></div>
      
      <div class="resumo-pagamento">
        <div class="resumo-linha">
          <span>Total selecionado:</span>
          <span class="valor-destaque" id="totalSelecionado">R$ 0,00</span>
        </div>
      </div>

      <div class="form-pagamento">
        <div class="form-group">
          <label>Valor a pagar (R$)</label>
          <input type="number" id="valorPagar" step="0.01" placeholder="0,00">
        </div>
        <div class="form-group">
          <label>Forma de pagamento</label>
          <select id="formaPagamento">
            <option value="">Selecione...</option>
            {% for forma in formas %}
            <option value="{{ forma }}">{{ forma }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Observação (opcional)</label>
        <input type="text" id="observacao" placeholder="Ex: Pagamento referente a...">
      </div>
      
      <button class="btn-pagar" id="btnPagar">✅ Realizar Pagamento</button>
    </div>
  </div>

  <!-- Adiantamento -->
  <div class="card">
    <div class="card-header">💸 Adiantamento (sem venda vinculada)</div>
    <div class="card-body">
      <div class="adiantamento-area">
        <div class="form-group">
          <label>Valor do adiantamento (R$)</label>
          <input type="number" id="valorAdiantamento" step="0.01" placeholder="0,00">
        </div>
        <div class="form-group">
          <label>Forma de pagamento</label>
          <select id="formaAdiantamento">
            <option value="">Selecione...</option>
            {% for forma in formas %}
            <option value="{{ forma }}">{{ forma }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Observação</label>
          <input type="text" id="obsAdiantamento" placeholder="Motivo do adiantamento">
        </div>
        <button class="btn-adiantar" id="btnAdiantar">💸 Registrar Adiantamento</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- Modal Recibo -->
<div id="modalRecibo" class="modal">
  <div class="modal-content">
    <div class="modal-header">📄 Recibo de Pagamento</div>
    <div class="modal-body" id="reciboBody"></div>
    <div class="modal-footer">
      <button class="btn-modal" onclick="fecharModal()">Fechar</button>
      <button class="btn-modal" onclick="imprimirRecibo()">🖨️ Imprimir</button>
    </div>
  </div>
</div>

<script>
let produtorAtual = null;
let vendasPendentes = [];
let vendasSelecionadas = new Set();

function toast(msg, tipo='ok') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${tipo}`;
  setTimeout(() => t.classList.remove('show'), 3000);
}

const fmt = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits:2});
const fmtKg = v => Number(v).toLocaleString('pt-BR', {minimumFractionDigits:3}) + ' kg';

document.getElementById('btnBuscar').onclick = async () => {
  const matricula = document.getElementById('matricula').value.trim();
  if (!matricula) { toast('Digite uma matrícula!', 'err'); return; }
  
  try {
    const res = await fetch('/api/pagamentos/buscar-produtor', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({matricula})
    });
    const data = await res.json();
    
    if (!data.encontrado) {
      toast('❌ Produtor não encontrado!', 'err');
      document.getElementById('produtorInfo').innerHTML = '';
      document.getElementById('produtorInfo').classList.remove('show');
      document.getElementById('cardVendas').style.display = 'none';
      return;
    }
    
    produtorAtual = data.produtor;
    document.getElementById('produtorInfo').innerHTML = `
      <div class="nome">👤 ${data.produtor.nome}</div>
      <div>Matrícula: ${data.produtor.matricula} | CPF: ${data.produtor.cpf || '---'}</div>
      <div class="saldo">Saldo pendente: ${fmt(data.saldo_total)}</div>
    `;
    document.getElementById('produtorInfo').classList.add('show');
    
    // Carregar vendas pendentes
    await carregarVendas(produtorAtual.id);
    
  } catch(e) {
    toast('Erro ao buscar produtor', 'err');
  }
};

async function carregarVendas(produtorId) {
  try {
    const res = await fetch('/api/pagamentos/vendas-pendentes', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({produtor_id: produtorId})
    });
    const data = await res.json();
    vendasPendentes = data.vendas;
    vendasSelecionadas.clear();
    renderizarVendas();
    
    if (vendasPendentes.length > 0) {
      document.getElementById('cardVendas').style.display = 'block';
    } else {
      document.getElementById('cardVendas').style.display = 'none';
      toast('✅ Produtor não possui vendas pendentes!', 'ok');
    }
  } catch(e) {
    toast('Erro ao carregar vendas', 'err');
  }
}

function renderizarVendas() {
  const container = document.getElementById('vendasLista');
  
  if (!vendasPendentes.length) {
    container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--muted)">Nenhuma venda pendente</div>';
    return;
  }
  
  container.innerHTML = vendasPendentes.map(v => `
    <div class="venda-item ${vendasSelecionadas.has(v.id) ? 'selecionado' : ''}" onclick="toggleVenda(${v.id})">
      <div class="venda-check">
        <input type="checkbox" ${vendasSelecionadas.has(v.id) ? 'checked' : ''} onclick="event.stopPropagation();toggleVenda(${v.id})">
      </div>
      <div class="venda-info">
        <div class="venda-data">📅 ${v.data}</div>
        <div class="venda-produto">${v.tipo} ${v.classe}</div>
        <div>${fmtKg(v.peso)}</div>
        <div class="venda-valor">${fmt(v.valor_produtor)}</div>
        <div><span class="venda-status ${v.status === 'Pendente' ? 'status-pendente' : 'status-parcial'}">${v.status}</span></div>
      </div>
    </div>
  `).join('');
  
  atualizarTotalSelecionado();
}

function toggleVenda(id) {
  if (vendasSelecionadas.has(id)) {
    vendasSelecionadas.delete(id);
  } else {
    vendasSelecionadas.add(id);
  }
  renderizarVendas();
}

function atualizarTotalSelecionado() {
  const total = vendasPendentes
    .filter(v => vendasSelecionadas.has(v.id))
    .reduce((sum, v) => sum + v.saldo, 0);
  
  document.getElementById('totalSelecionado').innerHTML = fmt(total);
  document.getElementById('valorPagar').value = total.toFixed(2);
}

document.getElementById('btnPagar').onclick = async () => {
  if (!produtorAtual) { toast('Selecione um produtor primeiro!', 'err'); return; }
  if (vendasSelecionadas.size === 0) { toast('Selecione pelo menos uma venda!', 'err'); return; }
  
  const valor = parseFloat(document.getElementById('valorPagar').value);
  const forma = document.getElementById('formaPagamento').value;
  const obs = document.getElementById('observacao').value;
  
  if (!forma) { toast('Selecione a forma de pagamento!', 'err'); return; }
  if (!valor || valor <= 0) { toast('Valor inválido!', 'err'); return; }
  
  const vendasIds = Array.from(vendasSelecionadas);
  const totalDisponivel = vendasPendentes
    .filter(v => vendasSelecionadas.has(v.id))
    .reduce((sum, v) => sum + v.saldo, 0);
  
  if (valor > totalDisponivel + 0.01) {
    toast(`Valor excede o total disponível (${fmt(totalDisponivel)})`, 'err');
    return;
  }
  
  const btn = document.getElementById('btnPagar');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Processando...';
  
  try {
    const res = await fetch('/api/pagamentos/registrar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        produtor_id: produtorAtual.id,
        vendas_ids: vendasIds,
        valor_pago: valor,
        forma_pagamento: forma,
        observacao: obs
      })
    });
    const data = await res.json();
    
    if (data.sucesso) {
      toast(data.mensagem, 'ok');
      // Gerar recibo
      await gerarRecibo(data.pagamento_id);
      // Recarregar vendas
      await carregarVendas(produtorAtual.id);
      document.getElementById('observacao').value = '';
    } else {
      toast(data.mensagem, 'err');
    }
  } catch(e) {
    toast('Erro ao processar pagamento', 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '✅ Realizar Pagamento';
  }
};

document.getElementById('btnAdiantar').onclick = async () => {
  if (!produtorAtual) { toast('Selecione um produtor primeiro!', 'err'); return; }
  
  const valor = parseFloat(document.getElementById('valorAdiantamento').value);
  const forma = document.getElementById('formaAdiantamento').value;
  const obs = document.getElementById('obsAdiantamento').value;
  
  if (!forma) { toast('Selecione a forma de pagamento!', 'err'); return; }
  if (!valor || valor <= 0) { toast('Valor inválido!', 'err'); return; }
  
  if (!confirm(`Confirmar adiantamento de ${fmt(valor)} para ${produtorAtual.nome}?`)) return;
  
  const btn = document.getElementById('btnAdiantar');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Processando...';
  
  try {
    const res = await fetch('/api/pagamentos/adiantar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        produtor_id: produtorAtual.id,
        valor: valor,
        forma_pagamento: forma,
        observacao: obs
      })
    });
    const data = await res.json();
    
    if (data.sucesso) {
      toast(data.mensagem, 'ok');
      await gerarRecibo(data.pagamento_id);
      document.getElementById('valorAdiantamento').value = '';
      document.getElementById('obsAdiantamento').value = '';
      await carregarVendas(produtorAtual.id);
    } else {
      toast(data.mensagem, 'err');
    }
  } catch(e) {
    toast('Erro ao registrar adiantamento', 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💸 Registrar Adiantamento';
  }
};

async function gerarRecibo(pagamentoId) {
  try {
    const res = await fetch('/api/pagamentos/recibo', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pagamento_id: pagamentoId})
    });
    const data = await res.json();
    
    if (data.sucesso) {
      let vendasHtml = '';
      data.recibo.vendas.forEach(v => {
        vendasHtml += `
          <div class="recibo-linha">
            <span>Venda #${v.id} - ${v.data}</span>
            <span>${v.tipo} ${v.classe} (${fmtKg(v.peso)})</span>
            <span>${fmt(v.pago)}</span>
          </div>
        `;
      });
      
      document.getElementById('reciboBody').innerHTML = `
        <div style="text-align:center;margin-bottom:1rem">
          <strong>COOPERATIVA AGRÍCOLA COPAR</strong><br>
          <small>CNPJ: 10.172.309/0001-12</small>
        </div>
        <div class="recibo-linha"><strong>Produtor:</strong> ${data.recibo.produtor.nome}</div>
        <div class="recibo-linha"><strong>Matrícula:</strong> ${data.recibo.produtor.matricula}</div>
        <div class="recibo-linha"><strong>CPF:</strong> ${data.recibo.produtor.cpf}</div>
        <div class="recibo-linha"><strong>Data:</strong> ${data.recibo.pagamento.data}</div>
        <div class="recibo-linha"><strong>Forma:</strong> ${data.recibo.pagamento.forma}</div>
        <hr style="margin:.5rem 0">
        <div style="font-weight:700;margin:.5rem 0">Vendas pagas:</div>
        ${vendasHtml}
        <hr style="margin:.5rem 0">
        <div class="recibo-linha" style="font-size:1rem;font-weight:700">
          <span>VALOR PAGO:</span>
          <span>${fmt(data.recibo.pagamento.valor)}</span>
        </div>
        ${data.recibo.pagamento.obs ? `<div class="recibo-linha"><strong>Obs:</strong> ${data.recibo.pagamento.obs}</div>` : ''}
        <div style="margin-top:1rem;text-align:center;font-size:.75rem;color:var(--muted)">
          Documento emitido eletronicamente
        </div>
      `;
      document.getElementById('modalRecibo').style.display = 'flex';
    }
  } catch(e) {
    console.error(e);
  }
}

function fecharModal() {
  document.getElementById('modalRecibo').style.display = 'none';
}

function imprimirRecibo() {
  const conteudo = document.getElementById('reciboBody').innerHTML;
  const win = window.open('', '_blank');
  win.document.write(`
    <html>
    <head>
      <title>Recibo COPAR</title>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
      <style>
        body{font-family:'IBM Plex Sans',sans-serif;padding:2rem;max-width:600px;margin:0 auto}
        .recibo-linha{display:flex;justify-content:space-between;margin-bottom:.5rem}
        hr{margin:.5rem 0}
      </style>
    </head>
    <body>${conteudo}</body>
    </html>
  `);
  win.print();
}

document.getElementById('matricula').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') document.getElementById('btnBuscar').click();
});
</script>
</body>
</html>
"""


# ============================================
# ROTAS
# ============================================

def registrar_rotas_pagamentos(app):
    @app.route('/pagamentos')
    def pagamentos():
        if not verificar_acesso():
            return "Acesso negado", 403
        return render_template_string(HTML_PAGAMENTOS, formas=FORMAS_PAGAMENTO)

    @app.route('/api/pagamentos/buscar-produtor', methods=['POST'])
    def api_buscar_produtor():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        matricula = data.get('matricula', '').strip()
        
        produtor = buscar_produtor_por_matricula(matricula)
        if not produtor:
            return jsonify({'encontrado': False})
        
        vendas = buscar_vendas_pendentes(produtor['id'])
        saldo_total = sum(v['saldo'] for v in vendas)
        
        return jsonify({
            'encontrado': True,
            'produtor': produtor,
            'saldo_total': saldo_total
        })

    @app.route('/api/pagamentos/vendas-pendentes', methods=['POST'])
    def api_vendas_pendentes():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        produtor_id = data.get('produtor_id')
        
        vendas = buscar_vendas_pendentes(produtor_id)
        return jsonify({'vendas': vendas})

    @app.route('/api/pagamentos/registrar', methods=['POST'])
    def api_registrar_pagamento():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        result = registrar_pagamento(
            data.get('produtor_id'),
            data.get('vendas_ids', []),
            float(data.get('valor_pago', 0)),
            data.get('forma_pagamento'),
            data.get('observacao', '')
        )
        return jsonify(result)

    @app.route('/api/pagamentos/adiantar', methods=['POST'])
    def api_adiantar():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        result = registrar_adiantamento(
            data.get('produtor_id'),
            float(data.get('valor', 0)),
            data.get('forma_pagamento'),
            data.get('observacao', '')
        )
        return jsonify(result)

    @app.route('/api/pagamentos/recibo', methods=['POST'])
    def api_recibo():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        
        data = request.get_json()
        recibo = gerar_recibo(data.get('produtor_id'), data.get('pagamento_id'))
        if recibo:
            return jsonify({'sucesso': True, 'recibo': recibo})
        return jsonify({'sucesso': False, 'mensagem': 'Erro ao gerar recibo'})

    print("✅ Módulo de Pagamentos carregado! Acesse: /pagamentos")
