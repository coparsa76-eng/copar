# -*- coding: utf-8 -*-
"""
MÓDULO DE VENDAS RÁPIDAS
- Seletor com Indústria 2 a 7 + Classes 2 a 7
- Aplica comissão COPAR (R$ 0,30/kg) automaticamente
- Aplica descontos extras configuráveis
- Registra na caixa COPAR
"""
from flask import render_template_string, jsonify, request, session
import psycopg
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'

TIPOS_ALHO = ['Ito', 'Chonan', 'São Valentim']
TIPOS_ESTOQUE = ['Classificação', 'Banca', 'Toletagem']

# Classes comerciais disponíveis para venda
# Cada uma vai como "classe" no banco: "Classe 2"..."Classe 7", "Indústria 2"..."Indústria 7"
CLASSES = [
    'Classe 2', 'Classe 3', 'Classe 4', 'Classe 5', 'Classe 6', 'Classe 7',
    'Indústria 2', 'Indústria 3', 'Indústria 4', 'Indústria 5', 'Indústria 6', 'Indústria 7',
]


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


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES (importadas do módulo de configurações)
# ══════════════════════════════════════════════════════════════════════════

def _obter_configuracoes():
    try:
        from modulo_configuracoes import obter_configuracoes
        return obter_configuracoes()
    except Exception as e:
        logger.error(f"Erro ao importar configurações: {e}")
        return {}


def _obter_comissao_por_kg():
    try:
        from modulo_configuracoes import obter_comissao_por_kg
        return obter_comissao_por_kg()
    except Exception:
        return 0.30


def _listar_descontos_ativos():
    try:
        from modulo_configuracoes import listar_descontos
        return [d for d in listar_descontos() if d.get('ativo')]
    except Exception:
        return []


def _registrar_comissao_copar(venda_id, produtor_id, peso_kg, valor, descricao):
    try:
        from modulo_configuracoes import registrar_comissao_copar
        return registrar_comissao_copar(venda_id, produtor_id, peso_kg, valor, descricao)
    except Exception as e:
        logger.error(f"Erro ao registrar comissão COPAR: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════
# CÁLCULO DE VALORES DA VENDA
# ══════════════════════════════════════════════════════════════════════════

def calcular_valores_venda(peso, valor_kg, comissao_por_kg, descontos_ativos):
    """
    Calcula:
    - valor_bruto = peso × valor_kg
    - comissao_copar = peso × comissao_por_kg
    - descontos extras (% sobre valor + R$ fixo)
    - valor_liquido_produtor = valor_bruto - comissao_copar - descontos_extras
    """
    valor_bruto = round(peso * valor_kg, 2)
    comissao_copar = round(peso * comissao_por_kg, 2)

    descontos_pct_valor = 0.0
    descontos_fixo = 0.0
    detalhes_descontos = []

    for d in descontos_ativos:
        tipo = d.get('tipo')
        valor_d = float(d.get('valor', 0))
        nome_d = d.get('nome', 'Desconto')

        if tipo == 'percentual_valor':
            vl = round(valor_bruto * (valor_d / 100.0), 2)
            descontos_pct_valor += vl
            detalhes_descontos.append({
                'nome': nome_d,
                'tipo': 'percentual_valor',
                'percentual': valor_d,
                'valor_calculado': vl,
            })
        elif tipo == 'valor_fixo':
            descontos_fixo += valor_d
            detalhes_descontos.append({
                'nome': nome_d,
                'tipo': 'valor_fixo',
                'percentual': 0,
                'valor_calculado': round(valor_d, 2),
            })

    descontos_extra = round(descontos_pct_valor + descontos_fixo, 2)
    valor_liquido = round(valor_bruto - comissao_copar - descontos_extra, 2)
    if valor_liquido < 0:
        valor_liquido = 0.0

    return {
        'valor_bruto': valor_bruto,
        'comissao_copar': comissao_copar,
        'descontos_extra': descontos_extra,
        'detalhes_descontos': detalhes_descontos,
        'valor_liquido': valor_liquido,
        'valor_produtor': valor_liquido,
    }


# ══════════════════════════════════════════════════════════════════════════
# BUSCAS
# ══════════════════════════════════════════════════════════════════════════

def buscar_produtor_por_matricula_local(matricula, tipo_alho, classe, local_estoque):
    """Busca produtor pela matrícula e retorna estoque disponível"""
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.nome, p.matricula, COALESCE(SUM(e.peso), 0) as peso_disponivel
            FROM produtores p
            LEFT JOIN estoque e ON p.id = e.produtor_id
                AND e.tipo_alho = %s AND e.classe = %s
                AND e.local_estoque = %s AND e.peso > 0
            WHERE p.matricula = %s
            GROUP BY p.id, p.nome, p.matricula
        """, (tipo_alho, classe, local_estoque, matricula.strip()))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                'id': row[0],
                'nome': row[1],
                'matricula': row[2],
                'peso_disponivel': float(row[3]),
            }
        return None
    except Exception as e:
        logger.error(f"Erro buscar_produtor_matricula: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════
# REGISTRAR VENDA
# ══════════════════════════════════════════════════════════════════════════

def registrar_venda(produtor_id, tipo_alho, classe, local_origem, peso, valor_kg):
    """
    Registra venda com:
    - Comissão COPAR (peso × R$ 0,30)
    - Descontos extras
    - Valor líquido ao produtor
    - Insere na caixa COPAR
    - Baixa o estoque (FIFO)
    """
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}

    try:
        cur = conn.cursor()

        # 1. Verifica estoque disponível
        cur.execute("""
            SELECT COALESCE(SUM(peso), 0) FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s 
              AND classe = %s AND local_estoque = %s AND peso > 0
        """, (produtor_id, tipo_alho, classe, local_origem))
        disp = float(cur.fetchone()[0])

        if disp < peso - 0.001:
            raise ValueError(f"Estoque insuficiente! Disponível: {disp:.3f} kg")

        # 2. Calcula valores
        comissao_por_kg = _obter_comissao_por_kg()
        descontos_ativos = _listar_descontos_ativos()
        valores = calcular_valores_venda(peso, valor_kg, comissao_por_kg, descontos_ativos)

        # 3. Insere a venda
        cur.execute("""
            INSERT INTO vendas (
                produtor_id, tipo_alho, classe, peso, valor_kg,
                valor_total, valor_produtor,
                desconto_comissao, desconto_extra,
                valor_liquido_produtor,
                comprador, origem_estoque, status_pagamento
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            produtor_id, tipo_alho, classe, peso, valor_kg,
            valores['valor_bruto'], valores['valor_produtor'],
            valores['comissao_copar'], valores['descontos_extra'],
            valores['valor_liquido'],
            'Venda Rápida', local_origem, 'Pendente'
        ))
        venda_id = cur.fetchone()[0]

        # 4. Registra o crédito do produtor
        cur.execute("""
            INSERT INTO creditos_produtor (produtor_id, venda_id, valor_credito, saldo)
            VALUES (%s, %s, %s, %s)
        """, (produtor_id, venda_id, valores['valor_produtor'], valores['valor_produtor']))

        # 5. Baixa o estoque (FIFO)
        cur.execute("""
            SELECT id, peso FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s
              AND classe = %s AND local_estoque = %s AND peso > 0
            ORDER BY data_registro, id
            FOR UPDATE
        """, (produtor_id, tipo_alho, classe, local_origem))
        rows = cur.fetchall()
        restante = peso
        for eid, epeso in rows:
            if restante <= 0.001:
                break
            epeso = float(epeso)
            if restante >= epeso - 0.001:
                cur.execute("DELETE FROM estoque WHERE id = %s", (eid,))
                restante -= epeso
            else:
                cur.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                            (round(epeso - restante, 4), eid))
                restante = 0

        # 6. Registra comissão na caixa COPAR (na mesma transação!)
        if valores['comissao_copar'] > 0:
            cur.execute("""
                INSERT INTO caixa_copar 
                    (venda_id, produtor_id, tipo_movimento, peso_kg, valor, descricao)
                VALUES (%s, %s, 'comissao', %s, %s, %s)
            """, (
                venda_id, produtor_id, peso, valores['comissao_copar'],
                f'Comissão venda #{venda_id} — {peso:.2f}kg × R$ {comissao_por_kg:.2f}'
            ))

        conn.commit()
        cur.close()
        conn.close()

        return {
            'sucesso': True,
            'mensagem': f'Venda #{venda_id} registrada!',
            'venda_id': venda_id,
            'valor_bruto': valores['valor_bruto'],
            'comissao_copar': valores['comissao_copar'],
            'descontos_extra': valores['descontos_extra'],
            'valor_produtor': valores['valor_produtor'],
        }

    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro registrar_venda: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


# ══════════════════════════════════════════════════════════════════════════
# HTML DA TELA
# ══════════════════════════════════════════════════════════════════════════

HTML_VENDAS = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Vendas – COPAR</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --verde:#1a5c2a;--verde2:#2d7a3f;--verde-pale:#eef6f0;--verde-light:#d4edda;
  --amber:#b45309;--amber-pale:#fef3c7;
  --red:#c0392b;--red-pale:#fde8e8;
  --blue:#1e4a8c;--blue-pale:#e8eef8;
  --ind:#8e44ad;--ind-pale:#f4ecf7;
  --text:#111827;--muted:#6b7280;--border:#d1d5db;
  --white:#fff;--bg:#f3f4f6;
  --radius:10px;--mono:'IBM Plex Mono',monospace;
  --shadow:0 2px 12px rgba(0,0,0,.08);
}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100dvh}

nav{background:var(--verde);padding:.75rem 1.25rem;display:flex;align-items:center;
    justify-content:space-between;position:sticky;top:0;z-index:100;gap:.75rem}
.nav-brand{color:#fff;font-weight:700;font-size:1.1rem}
.nav-back{color:rgba(255,255,255,.85);text-decoration:none;font-size:.82rem;
          border:1px solid rgba(255,255,255,.3);padding:.4rem .9rem;border-radius:8px}
.nav-back:hover{background:rgba(255,255,255,.15)}

.wrap{max-width:900px;margin:0 auto;padding:1.25rem}

.config-card{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow);
             margin-bottom:1rem;overflow:hidden}
.config-header{background:var(--verde);color:#fff;padding:.75rem 1.1rem;font-weight:700;font-size:.9rem}
.config-body{padding:1rem 1.1rem;display:grid;gap:.75rem}
.config-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
@media(min-width:600px){.config-row{grid-template-columns:1fr 1fr 1fr}}

label{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
      color:var(--muted);display:block;margin-bottom:.3rem}
select,input[type=number],input[type=text]{
  width:100%;padding:.6rem .8rem;border:1.5px solid var(--border);border-radius:8px;
  font-family:'IBM Plex Sans',sans-serif;font-size:.9rem;color:var(--text);
  background:var(--white);transition:border-color .15s;-webkit-appearance:none}
select:focus,input:focus{outline:none;border-color:var(--verde)}

.valor-wrap{position:relative;max-width:200px}
.valor-wrap input{padding-left:2rem;font-family:var(--mono);font-weight:600;
                  background:var(--amber-pale);border-color:#f59e0b}
.valor-prefixo{position:absolute;left:.75rem;top:50%;transform:translateY(-50%);
               color:var(--amber);font-weight:700;font-family:var(--mono);font-size:.9rem}

.produtores-area{margin-bottom:1rem}
.prod-row{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow);
          padding:.9rem 1rem;margin-bottom:.6rem;border-left:4px solid var(--border)}
.prod-row.ok{border-left-color:var(--verde)}
.prod-row.erro{border-left-color:var(--red)}

.prod-fields{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;align-items:end}
@media(min-width:480px){.prod-fields{grid-template-columns:180px 1fr auto}}

.prod-info{margin-top:.5rem;font-size:.8rem;padding:.4rem .7rem;border-radius:6px;display:none}
.prod-info.show{display:block}
.prod-info.ok{background:var(--verde-light);color:var(--verde)}
.prod-info.warn{background:var(--amber-pale);color:var(--amber)}
.prod-info.err{background:var(--red-pale);color:var(--red)}

.btn-rem{background:var(--red-pale);border:none;color:var(--red);width:32px;height:32px;
         border-radius:8px;cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center}
.btn-rem:hover{background:var(--red);color:#fff}

.btn-add{width:100%;background:var(--verde-pale);border:2px dashed var(--verde);
         color:var(--verde);padding:.7rem;border-radius:var(--radius);
         font-weight:700;font-size:.88rem;cursor:pointer;
         display:flex;align-items:center;justify-content:center;gap:.5rem;
         font-family:inherit;margin-bottom:1rem}
.btn-add:hover{background:var(--verde-light)}

.carrinho{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden;margin-bottom:1rem}
.carr-header{background:#111827;color:#fff;padding:.75rem 1.1rem;font-weight:700;
             font-size:.9rem;display:flex;align-items:center;justify-content:space-between}
.carr-empty{padding:1.5rem;text-align:center;color:var(--muted);font-size:.88rem}
.carr-table{width:100%;border-collapse:collapse;font-size:.84rem}
.carr-table th{background:var(--bg);color:var(--muted);padding:.55rem .85rem;text-align:left;
               font-size:.72rem;font-weight:700;text-transform:uppercase}
.carr-table td{padding:.65rem .85rem;border-bottom:1px solid var(--border)}
.carr-table .mono{font-family:var(--mono);font-weight:600}

.totais{padding:.9rem 1.1rem;background:var(--verde-pale);border-top:2px solid var(--verde-light);
        display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem}
.totais .bloco{display:flex;flex-direction:column;gap:.15rem}
.totais .bloco.dir{text-align:right}
.total-label{font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--muted);letter-spacing:.04em}
.total-val{font-family:var(--mono);font-weight:700;font-size:1.05rem;color:var(--verde)}
.total-val.amber{color:var(--amber)}
.total-val.blue{color:var(--blue)}

.acoes{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:1.5rem}
.btn-finalizar{background:var(--verde);border:none;color:#fff;padding:.85rem;
               border-radius:var(--radius);font-weight:700;font-size:1rem;cursor:pointer;font-family:inherit}
.btn-finalizar:hover{background:var(--verde2)}
.btn-finalizar:disabled{opacity:.5;cursor:not-allowed}
.btn-limpar{background:var(--red-pale);border:1.5px solid var(--red);color:var(--red);
            padding:.85rem;border-radius:var(--radius);font-weight:700;font-size:.9rem;
            cursor:pointer;font-family:inherit}
.btn-limpar:hover{background:var(--red);color:#fff}

.toast{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%) translateY(100px);
       background:#111;color:#fff;padding:.75rem 1.5rem;border-radius:999px;font-size:.88rem;
       font-weight:600;z-index:999;transition:transform .3s;max-width:90%;text-align:center}
.toast.show{transform:translateX(-50%) translateY(0)}
.toast.ok{background:var(--verde)}
.toast.err{background:var(--red)}

.spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);
      border-top-color:#fff;border-radius:50%;animation:sp .6s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}

.tag-ind{background:var(--ind-pale);color:var(--ind);padding:.1rem .4rem;border-radius:4px;font-size:.68rem;font-weight:700}
.tag-cls{background:#e0e7ff;color:#3730a3;padding:.1rem .4rem;border-radius:4px;font-size:.68rem;font-weight:700}
</style>
</head>
<body>
<nav>
  <div class="nav-brand">COPAR — Vendas</div>
  <a href="/gerente" class="nav-back">Voltar</a>
</nav>

<div class="wrap">

  <div class="config-card">
    <div class="config-header">Configuração da Venda</div>
    <div class="config-body">
      <div class="config-row">
        <div>
          <label>Origem / Local</label>
          <select id="local">
            <option value="">Selecione...</option>
            {% for l in locais %}<option>{{ l }}</option>{% endfor %}
          </select>
        </div>
        <div>
          <label>Variedade</label>
          <select id="tipo">
            <option value="">Selecione...</option>
            {% for t in tipos_alho %}<option>{{ t }}</option>{% endfor %}
          </select>
        </div>
        <div>
          <label>Classe</label>
          <select id="classe">
            <option value="">Selecione...</option>
            <optgroup label="Classes Comuns">
              {% for c in classes_comuns %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
            </optgroup>
            <optgroup label="Indústria (por classe de origem)">
              {% for i in industrias %}<option value="{{ i }}">{{ i }}</option>{% endfor %}
            </optgroup>
          </select>
        </div>
      </div>
      <div>
        <label>Valor por Kg</label>
        <div class="valor-wrap">
          <span class="valor-prefixo">R$</span>
          <input type="number" id="valorKg" min="0" step="0.01" placeholder="0,00">
        </div>
      </div>
    </div>
  </div>

  <div id="produtoresArea" class="produtores-area"></div>
  <button class="btn-add" id="btnAddLinha">+ Adicionar Produtor</button>

  <div class="carrinho">
    <div class="carr-header">
      <span>Carrinho</span>
      <span id="carrCount" style="background:rgba(255,255,255,.2);border-radius:999px;padding:.1rem .6rem;font-size:.8rem">0 itens</span>
    </div>
    <div id="carrBody">
      <div class="carr-empty">Nenhum item adicionado</div>
    </div>
    <div class="totais">
      <div class="bloco">
        <div class="total-label">Total da Venda</div>
        <div class="total-val" id="totalVenda">R$ 0,00</div>
      </div>
      <div class="bloco" style="text-align:center">
        <div class="total-label">Comissão COPAR</div>
        <div class="total-val amber" id="totalComissao">R$ 0,00</div>
      </div>
      <div class="bloco dir">
        <div class="total-label">Líquido Produtores</div>
        <div class="total-val blue" id="totalProdutor">R$ 0,00</div>
      </div>
    </div>
  </div>

  <div class="acoes">
    <button class="btn-finalizar" id="btnFinalizar" disabled>Finalizar Venda</button>
    <button class="btn-limpar" id="btnLimpar">Limpar Tudo</button>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const COMISSAO_POR_KG = {{ comissao_por_kg }};

const fmt = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtKg = v => Number(v).toLocaleString('pt-BR', {minimumFractionDigits:3, maximumFractionDigits:3}) + ' kg';

let carrinho = [];
let linhaId = 0;

function toast(msg, tipo='ok', dur=3000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${tipo}`;
  setTimeout(() => t.classList.remove('show'), dur);
}

function getConfig() {
  const local = document.getElementById('local').value;
  const tipo = document.getElementById('tipo').value;
  const classe = document.getElementById('classe').value;
  const valor = parseFloat(document.getElementById('valorKg').value);
  if (!local || !tipo || !classe || !valor || valor <= 0) return null;
  return { local, tipo, classe, valor };
}

function classeTag(classe) {
  if (classe.startsWith('Indústria')) return `<span class="tag-ind">${classe}</span>`;
  return `<span class="tag-cls">${classe}</span>`;
}

function criarLinha() {
  const cfg = getConfig();
  if (!cfg) { toast('Preencha origem, variedade, classe e valor/kg antes!', 'err'); return; }

  const id = linhaId++;
  const div = document.createElement('div');
  div.className = 'prod-row';
  div.id = `linha-${id}`;
  div.innerHTML = `
    <div class="prod-fields">
      <div>
        <label>Matrícula</label>
        <input type="text" id="mat-${id}" placeholder="Ex: 0042" autocomplete="off"
               onblur="verificarProdutor(${id})" onkeydown="if(event.key==='Enter')verificarProdutor(${id})">
      </div>
      <div>
        <label>Peso (kg) <span id="disp-${id}" style="font-size:.72rem;color:var(--muted)"></span></label>
        <input type="number" id="peso-${id}" placeholder="0.000" step="0.001" min="0.001"
               oninput="validarPeso(${id})" disabled>
      </div>
      <div style="display:flex;align-items:flex-end;padding-bottom:1px">
        <button class="btn-rem" onclick="removerLinha(${id})" title="Remover">X</button>
      </div>
    </div>
    <div class="prod-info" id="info-${id}"></div>
    <div style="margin-top:.6rem;display:none" id="add-${id}">
      <button onclick="adicionarCarrinho(${id})"
              style="background:var(--verde);color:#fff;border:none;padding:.5rem 1.2rem;
                     border-radius:8px;font-weight:700;font-size:.82rem;cursor:pointer;font-family:inherit;width:100%">
        Adicionar ao Carrinho
      </button>
    </div>
  `;
  document.getElementById('produtoresArea').appendChild(div);
  document.getElementById(`mat-${id}`).focus();
}

async function verificarProdutor(id) {
  const cfg = getConfig();
  if (!cfg) return;

  const mat = document.getElementById(`mat-${id}`).value.trim();
  if (!mat) return;

  const infoDiv = document.getElementById(`info-${id}`);
  const dispSpan = document.getElementById(`disp-${id}`);
  const pesoInput = document.getElementById(`peso-${id}`);
  const addDiv = document.getElementById(`add-${id}`);
  const linha = document.getElementById(`linha-${id}`);

  infoDiv.className = 'prod-info show';
  infoDiv.textContent = 'Verificando estoque...';

  try {
    const res = await fetch('/api/vendas-rapido/verificar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({matricula: mat, tipo_alho: cfg.tipo, classe: cfg.classe, local_estoque: cfg.local})
    });
    const data = await res.json();

    if (!data.encontrado) {
      infoDiv.className = 'prod-info show err';
      infoDiv.textContent = 'Matrícula não encontrada';
      linha.className = 'prod-row erro';
      pesoInput.disabled = true;
      addDiv.style.display = 'none';
      linha.dataset.produtorId = '';
      return;
    }

    linha.dataset.produtorId = data.id;
    linha.dataset.nome = data.nome;
    linha.dataset.matricula = data.matricula;
    linha.dataset.disponivel = data.peso_disponivel;

    if (data.peso_disponivel <= 0) {
      infoDiv.className = 'prod-info show warn';
      infoDiv.innerHTML = `<strong>${data.nome}</strong> — Sem estoque nesta combinação`;
      linha.className = 'prod-row erro';
      pesoInput.disabled = true;
      addDiv.style.display = 'none';
    } else {
      infoDiv.className = 'prod-info show ok';
      infoDiv.innerHTML = `<strong>${data.nome}</strong> — Disponível: <strong>${fmtKg(data.peso_disponivel)}</strong>`;
      linha.className = 'prod-row ok';
      dispSpan.textContent = `máx: ${fmtKg(data.peso_disponivel)}`;
      pesoInput.disabled = false;
      pesoInput.max = data.peso_disponivel;
      pesoInput.focus();
      addDiv.style.display = 'block';
    }
  } catch(e) {
    infoDiv.className = 'prod-info show err';
    infoDiv.textContent = 'Erro de comunicação';
  }
}

function validarPeso(id) {
  const linha = document.getElementById(`linha-${id}`);
  const pesoInput = document.getElementById(`peso-${id}`);
  const disp = parseFloat(linha.dataset.disponivel || 0);
  const peso = parseFloat(pesoInput.value || 0);
  if (peso > disp) {
    pesoInput.value = disp.toFixed(3);
    toast(`Peso máximo: ${fmtKg(disp)}`, 'err');
  }
}

function adicionarCarrinho(id) {
  const linha = document.getElementById(`linha-${id}`);
  const cfg = getConfig();
  if (!cfg) { toast('Configuração inválida', 'err'); return; }

  const produtorId = linha.dataset.produtorId;
  const nome = linha.dataset.nome;
  const matricula = linha.dataset.matricula;
  const disponivel = parseFloat(linha.dataset.disponivel || 0);
  const peso = parseFloat(document.getElementById(`peso-${id}`).value || 0);

  if (!produtorId) { toast('Verifique a matrícula primeiro', 'err'); return; }
  if (peso <= 0) { toast('Informe o peso!', 'err'); return; }
  if (peso > disponivel + 0.001) { toast(`Peso maior que disponível`, 'err'); return; }

  const duplicado = carrinho.find(i =>
    i.produtor_id == produtorId && i.tipo == cfg.tipo &&
    i.classe == cfg.classe && i.local == cfg.local
  );
  if (duplicado) { toast('Produtor já está no carrinho!', 'err'); return; }

  carrinho.push({
    id: Date.now(),
    produtor_id: produtorId,
    nome, matricula,
    tipo: cfg.tipo, classe: cfg.classe, local: cfg.local,
    peso, valor_kg: cfg.valor
  });

  renderCarrinho();
  removerLinha(id);
  toast(`${nome} adicionado`);
}

function removerLinha(id) { document.getElementById(`linha-${id}`)?.remove(); }
function removerCarrinho(id) {
  carrinho = carrinho.filter(i => i.id !== id);
  renderCarrinho();
}

function renderCarrinho() {
  const body = document.getElementById('carrBody');
  const count = document.getElementById('carrCount');
  const btnFin = document.getElementById('btnFinalizar');

  count.textContent = `${carrinho.length} ite${carrinho.length !== 1 ? 'ns' : 'm'}`;

  if (!carrinho.length) {
    body.innerHTML = '<div class="carr-empty">Nenhum item adicionado</div>';
    document.getElementById('totalVenda').textContent = 'R$ 0,00';
    document.getElementById('totalComissao').textContent = 'R$ 0,00';
    document.getElementById('totalProdutor').textContent = 'R$ 0,00';
    btnFin.disabled = true;
    return;
  }

  let totalVenda = 0, totalComissao = 0, totalLiquido = 0;
  const rows = carrinho.map(item => {
    const subtotal = item.peso * item.valor_kg;
    const comissao = item.peso * COMISSAO_POR_KG;
    const liquido = subtotal - comissao;
    totalVenda += subtotal;
    totalComissao += comissao;
    totalLiquido += liquido;
    return `
      <tr>
        <td>${item.matricula}</td>
        <td>${item.nome}</td>
        <td>${classeTag(item.classe)}<br><span style="font-size:.7rem;color:var(--muted)">${item.tipo} · ${item.local}</span></td>
        <td class="mono">${fmtKg(item.peso)}</td>
        <td class="mono">${fmt(item.valor_kg)}/kg</td>
        <td class="mono">${fmt(subtotal)}</td>
        <td class="mono" style="color:var(--amber)">-${fmt(comissao)}</td>
        <td class="mono" style="color:var(--blue)"><strong>${fmt(liquido)}</strong></td>
        <td><button class="btn-rem" onclick="removerCarrinho(${item.id})" style="width:24px;height:24px;font-size:.75rem">X</button></td>
      </tr>
    `;
  }).join('');

  body.innerHTML = `
    <table class="carr-table">
      <thead><tr>
        <th>Matr.</th><th>Produtor</th><th>Produto</th>
        <th>Peso</th><th>R$/kg</th><th>Bruto</th>
        <th>COPAR</th><th>Líquido</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  document.getElementById('totalVenda').textContent = fmt(totalVenda);
  document.getElementById('totalComissao').textContent = fmt(totalComissao);
  document.getElementById('totalProdutor').textContent = fmt(totalLiquido);
  btnFin.disabled = false;
}

document.getElementById('btnFinalizar').onclick = async function() {
  if (!carrinho.length) return;
  const totalVenda = carrinho.reduce((s, i) => s + i.peso * i.valor_kg, 0);
  const totalComissao = carrinho.reduce((s, i) => s + i.peso * COMISSAO_POR_KG, 0);
  if (!confirm(`Confirmar venda?\n\nTotal: ${fmt(totalVenda)}\nComissão COPAR: ${fmt(totalComissao)}\nProdutores recebem: ${fmt(totalVenda - totalComissao)}`)) return;

  this.disabled = true;
  this.innerHTML = '<span class="spin"></span> Registrando...';

  try {
    const res = await fetch('/api/vendas-rapido/finalizar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ itens: carrinho.map(i => ({
        produtor_id: i.produtor_id,
        tipo_alho: i.tipo,
        classe: i.classe,
        local_origem: i.local,
        peso: i.peso,
        valor_kg: i.valor_kg
      }))})
    });
    const data = await res.json();

    if (data.sucesso) {
      toast('Vendas registradas!', 'ok', 4000);
      carrinho = [];
      renderCarrinho();
      document.getElementById('produtoresArea').innerHTML = '';
    } else {
      toast(data.mensagem, 'err', 5000);
    }
  } catch(e) {
    toast('Erro de comunicação', 'err');
  } finally {
    this.disabled = false;
    this.innerHTML = 'Finalizar Venda';
  }
};

document.getElementById('btnAddLinha').onclick = criarLinha;

document.getElementById('btnLimpar').onclick = function() {
  if (!confirm('Limpar tudo?')) return;
  carrinho = [];
  renderCarrinho();
  document.getElementById('produtoresArea').innerHTML = '';
};

['local','tipo','classe','valorKg'].forEach(id => {
  document.getElementById(id).addEventListener('change', () => {
    if (carrinho.length > 0 || document.getElementById('produtoresArea').children.length > 0) {
      toast('Limpe o carrinho antes de mudar a configuração', 'err');
    }
  });
});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════════════════

def registrar_rotas_vendas_rapido(app):

    @app.route('/vendas/rapido')
    def vendas_rapido():
        if not verificar_acesso():
            return "Acesso negado", 403
        classes_comuns = ['Classe 2', 'Classe 3', 'Classe 4', 'Classe 5', 'Classe 6', 'Classe 7']
        industrias = ['Indústria 2', 'Indústria 3', 'Indústria 4', 'Indústria 5', 'Indústria 6', 'Indústria 7']
        return render_template_string(
            HTML_VENDAS,
            tipos_alho=TIPOS_ALHO,
            locais=TIPOS_ESTOQUE,
            classes_comuns=classes_comuns,
            industrias=industrias,
            comissao_por_kg=_obter_comissao_por_kg(),
        )

    @app.route('/api/vendas-rapido/verificar', methods=['POST'])
    def api_verificar_produtor():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        data = request.get_json()
        matricula = data.get('matricula', '').strip()
        tipo_alho = data.get('tipo_alho', '')
        classe = data.get('classe', '')
        local_estoque = data.get('local_estoque', '')

        if not all([matricula, tipo_alho, classe, local_estoque]):
            return jsonify({'encontrado': False, 'mensagem': 'Parâmetros incompletos'})

        produtor = buscar_produtor_por_matricula_local(matricula, tipo_alho, classe, local_estoque)
        if not produtor:
            return jsonify({'encontrado': False})

        return jsonify({
            'encontrado': True,
            'id': produtor['id'],
            'nome': produtor['nome'],
            'matricula': produtor['matricula'],
            'peso_disponivel': produtor['peso_disponivel']
        })

    @app.route('/api/vendas-rapido/finalizar', methods=['POST'])
    def api_finalizar():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        data = request.get_json()
        itens = data.get('itens', [])
        if not itens:
            return jsonify({'sucesso': False, 'mensagem': 'Nenhum item'})

        resultados = []
        for item in itens:
            result = registrar_venda(
                item['produtor_id'],
                item['tipo_alho'],
                item['classe'],
                item['local_origem'],
                float(item['peso']),
                float(item['valor_kg'])
            )
            if not result['sucesso']:
                return jsonify({'sucesso': False,
                                'mensagem': f"Erro em {item.get('produtor_id')}: {result['mensagem']}"})
            resultados.append(result)

        total = len(resultados)
        soma_comissao = sum(r.get('comissao_copar', 0) for r in resultados)
        return jsonify({
            'sucesso': True,
            'mensagem': f'{total} venda(s) registrada(s). Comissão COPAR: R$ {soma_comissao:.2f}'
        })

    print("✅ Módulo Vendas Rápidas carregado! (/vendas/rapido)")
