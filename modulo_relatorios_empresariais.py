# -*- coding: utf-8 -*-
"""
MÓDULO DE RELATÓRIOS EMPRESARIAIS
- Relatório individual do produtor (6 abas)
- Sem emojis, layout corporativo
- Mostra indústria por classe, horas de banca e comissões COPAR
"""
from flask import render_template_string, jsonify, request, session, redirect, url_for
import psycopg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'


def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro conexão: {e}")
        return None


def verificar_acesso_gerente():
    if 'produtor_id' not in session:
        return False
    return session.get('tipo') in ('gerente', 'superadmin')


def _obter_configuracoes():
    try:
        from modulo_configuracoes import obter_configuracoes
        return obter_configuracoes()
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════
# RELATÓRIO COMPLETO DO PRODUTOR
# ══════════════════════════════════════════════════════════════════════════

def obter_relatorio_produtor_completo(produtor_id):
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()

        # ── 1. Dados do produtor ─────────────────────────────────────────
        cur.execute("""
            SELECT id, nome, matricula, COALESCE(cpf, '')
            FROM produtores WHERE id = %s
        """, (produtor_id,))
        p = cur.fetchone()
        if not p:
            return None

        produtor = {'id': p[0], 'nome': p[1], 'matricula': p[2], 'cpf': p[3]}

        # ── 2. Estoque atual (com indústria separada) ────────────────────
        cur.execute("""
            SELECT local_estoque, tipo_alho, classe,
                   SUM(peso) AS total_peso
            FROM estoque
            WHERE produtor_id = %s AND peso > 0
            GROUP BY local_estoque, tipo_alho, classe
            ORDER BY local_estoque, tipo_alho, classe
        """, (produtor_id,))

        estoque = []
        estoque_industria = []  # separado para ficar em destaque
        for r in cur.fetchall():
            classe = r[2] or ''
            item = {
                'local': r[0],
                'tipo': r[1],
                'classe': classe,
                'peso': float(r[3]),
                'is_industria': classe.startswith('Indústria'),
            }
            if item['is_industria']:
                estoque_industria.append(item)
            else:
                estoque.append(item)

        # ── 3. Vendas detalhadas ─────────────────────────────────────────
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_kg,
                   v.valor_total, v.valor_produtor,
                   COALESCE(v.desconto_comissao, 0) AS comissao,
                   COALESCE(v.desconto_extra, 0) AS extra,
                   COALESCE(v.valor_liquido_produtor, v.valor_produtor) AS liquido,
                   v.status_pagamento, v.origem_estoque,
                   COALESCE(cp.saldo, v.valor_produtor) AS saldo,
                   COALESCE(cp.valor_pago, 0) AS pago
            FROM vendas v
            LEFT JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s
            ORDER BY v.data_venda DESC
        """, (produtor_id,))

        vendas = []
        for r in cur.fetchall():
            vendas.append({
                'id': r[0],
                'data': r[1].strftime("%d/%m/%Y") if r[1] else '',
                'tipo': r[2] or '',
                'classe': r[3] or '',
                'peso': float(r[4] or 0),
                'valor_kg': float(r[5] or 0),
                'valor_total': float(r[6] or 0),
                'valor_produtor': float(r[7] or 0),
                'comissao': float(r[8]),
                'extra': float(r[9]),
                'liquido': float(r[10]),
                'status': r[11],
                'origem': r[12] or '',
                'saldo': float(r[13] or 0),
                'pago': float(r[14] or 0),
                'is_industria': (r[3] or '').startswith('Indústria'),
            })

        # ── 4. Pagamentos ────────────────────────────────────────────────
        cur.execute("""
            SELECT id, data_pagamento, valor_total, forma_pagamento, observacoes
            FROM pagamentos WHERE produtor_id = %s
            ORDER BY data_pagamento DESC
        """, (produtor_id,))
        pagamentos = [{
            'id': r[0],
            'data': r[1].strftime("%d/%m/%Y %H:%M") if r[1] else '',
            'valor': float(r[2]),
            'forma': r[3],
            'obs': r[4] or '',
        } for r in cur.fetchall()]

        # ── 5. Horas de banca ────────────────────────────────────────────
        cur.execute("""
            SELECT id, tipo_alho, local_origem, local_destino, horas,
                   registrado_em, operador_nome
            FROM registros_horas_banca
            WHERE produtor_id = %s
            ORDER BY registrado_em DESC
        """, (produtor_id,))
        registros_hb = [{
            'id': r[0],
            'tipo': r[1] or '',
            'origem': r[2] or '',
            'destino': r[3] or '',
            'horas': float(r[4]),
            'data': r[5].strftime("%d/%m/%Y %H:%M") if r[5] else '',
            'operador': r[6] or '',
        } for r in cur.fetchall()]
        total_horas = sum(r['horas'] for r in registros_hb)

        # ── 6. Comissões COPAR pagas pelo produtor ────────────────────────
        cur.execute("""
            SELECT c.id, c.data_movimento, c.peso_kg, c.valor,
                   c.descricao, c.venda_id
            FROM caixa_copar c
            WHERE c.produtor_id = %s AND c.tipo_movimento = 'comissao'
            ORDER BY c.data_movimento DESC
        """, (produtor_id,))
        comissoes = [{
            'id': r[0],
            'data': r[1].strftime("%d/%m/%Y %H:%M") if r[1] else '',
            'peso': float(r[2]) if r[2] else 0,
            'valor': float(r[3]),
            'descricao': r[4] or '',
            'venda_id': r[5],
        } for r in cur.fetchall()]
        total_comissao_produtor = sum(c['valor'] for c in comissoes)

        # ── Resumo ────────────────────────────────────────────────────────
        total_vendas_bruto = sum(v['valor_total'] for v in vendas)
        total_comissoes = sum(v['comissao'] for v in vendas)
        total_extras = sum(v['extra'] for v in vendas)
        total_liquido = sum(v['liquido'] for v in vendas)
        total_pago = sum(p['valor'] for p in pagamentos)
        total_pendente = sum(v['saldo'] for v in vendas if v['saldo'] > 0)
        total_kg_vendido = sum(v['peso'] for v in vendas)
        total_kg_estoque = sum(e['peso'] for e in estoque) + sum(e['peso'] for e in estoque_industria)
        total_kg_industria_est = sum(e['peso'] for e in estoque_industria)

        cur.close()
        conn.close()

        return {
            'produtor': produtor,
            'estoque': estoque,
            'estoque_industria': estoque_industria,
            'vendas': vendas,
            'pagamentos': pagamentos,
            'registros_horas_banca': registros_hb,
            'comissoes': comissoes,
            'config': _obter_configuracoes(),
            'resumo': {
                'total_vendas_bruto': total_vendas_bruto,
                'total_comissoes': total_comissoes,
                'total_extras': total_extras,
                'total_liquido': total_liquido,
                'total_pago': total_pago,
                'total_pendente': total_pendente,
                'total_kg_vendido': total_kg_vendido,
                'total_kg_estoque': total_kg_estoque,
                'total_kg_industria_estoque': total_kg_industria_est,
                'total_horas_banca': total_horas,
                'total_comissao_produtor': total_comissao_produtor,
                'qtd_vendas': len(vendas),
                'qtd_pagamentos': len(pagamentos),
                'qtd_horas_registros': len(registros_hb),
                'qtd_comissoes': len(comissoes),
            },
            'data_geracao': datetime.now().strftime("%d/%m/%Y às %H:%M"),
        }
    except Exception as e:
        logger.error(f"Erro relatorio produtor: {e}")
        import traceback
        traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════════════
# HTML DO RELATÓRIO
# ══════════════════════════════════════════════════════════════════════════

HTML_RELATORIO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Relatório - {{ r.produtor.nome }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#0a3d2c;--primary-light:#1a6b4d;--accent:#b8935a;
  --gray-50:#f9fafb;--gray-100:#f3f4f6;--gray-200:#e5e7eb;
  --gray-300:#d1d5db;--gray-500:#6b7280;--gray-700:#374151;--gray-900:#111827;
  --red:#991b1b;--red-light:#fee2e2;--green:#166534;--green-light:#dcfce7;
  --amber:#92400e;--amber-light:#fef3c7;--blue:#1e40af;--blue-light:#dbeafe;
  --ind:#7c3aed;--ind-light:#ede9fe;
}
body{font-family:'Inter',sans-serif;background:#fff;color:var(--gray-900);font-size:13px;line-height:1.5}

.report{max-width:1050px;margin:0 auto;padding:2rem}

/* HEADER */
.header{border-bottom:3px solid var(--primary);padding-bottom:1.5rem;margin-bottom:2rem;display:flex;justify-content:space-between;align-items:flex-start;gap:2rem;flex-wrap:wrap}
.brand{flex:1;min-width:280px}
.brand-name{font-size:1.5rem;font-weight:800;color:var(--primary);letter-spacing:-.02em;margin-bottom:.25rem}
.brand-sub{font-size:.72rem;color:var(--gray-500);font-weight:500;text-transform:uppercase;letter-spacing:.12em}
.brand-info{margin-top:.75rem;font-size:.78rem;color:var(--gray-700);line-height:1.7}
.brand-info span{color:var(--gray-500)}
.report-meta{text-align:right;font-size:.75rem;color:var(--gray-500);min-width:200px}
.report-title{font-size:.95rem;font-weight:700;color:var(--gray-900);margin-bottom:.5rem;text-transform:uppercase;letter-spacing:.08em}
.report-id{display:inline-block;background:var(--gray-100);padding:.2rem .6rem;border-radius:4px;font-family:monospace;font-size:.72rem;color:var(--gray-700)}

/* IDENTIFICAÇÃO */
.identification{background:linear-gradient(135deg,var(--primary) 0%,var(--primary-light) 100%);color:#fff;padding:1.5rem;border-radius:8px;margin-bottom:2rem}
.identification h2{font-size:.68rem;text-transform:uppercase;letter-spacing:.15em;opacity:.75;margin-bottom:.75rem;font-weight:600}
.id-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1.5rem}
.id-item .label{font-size:.62rem;text-transform:uppercase;letter-spacing:.1em;opacity:.7;margin-bottom:.25rem}
.id-item .value{font-size:1.05rem;font-weight:600}
.id-item .value.mono{font-family:monospace;letter-spacing:.02em}

/* KPIs */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:2rem}
.kpi{border:1px solid var(--gray-200);border-radius:6px;padding:1rem 1.15rem;border-left:3px solid var(--primary);background:#fff}
.kpi.green{border-left-color:var(--green)}
.kpi.amber{border-left-color:var(--amber)}
.kpi.red{border-left-color:var(--red)}
.kpi.blue{border-left-color:var(--blue)}
.kpi.ind{border-left-color:var(--ind)}
.kpi .label{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:var(--gray-500);font-weight:600;margin-bottom:.4rem}
.kpi .value{font-size:1.35rem;font-weight:700;font-family:monospace;color:var(--gray-900);letter-spacing:-.02em}
.kpi .sub{font-size:.7rem;color:var(--gray-500);margin-top:.2rem}

/* TABS */
.tabs{display:flex;gap:0;border-bottom:2px solid var(--gray-200);margin-bottom:1.5rem;overflow-x:auto}
.tab{padding:.75rem 1.1rem;background:none;border:none;cursor:pointer;font-family:inherit;font-size:.78rem;font-weight:600;color:var(--gray-500);text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s;white-space:nowrap}
.tab:hover{color:var(--primary)}
.tab.active{color:var(--primary);border-bottom-color:var(--primary)}

.tab-panel{display:none}
.tab-panel.active{display:block}

/* SECTION */
.section{margin-bottom:2rem}
.section-title{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--primary);margin-bottom:.75rem;padding-bottom:.4rem;border-bottom:1px solid var(--gray-200);display:flex;justify-content:space-between;align-items:center}
.section-total{font-family:monospace;color:var(--gray-700);font-weight:600}

/* TABELAS */
table{width:100%;border-collapse:collapse;font-size:.78rem;background:#fff}
thead{background:var(--gray-50)}
th{text-align:left;padding:.6rem .75rem;font-size:.66rem;font-weight:700;color:var(--gray-500);text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--gray-300);white-space:nowrap}
th.num,td.num{text-align:right;font-family:monospace}
td{padding:.6rem .75rem;border-bottom:1px solid var(--gray-100);color:var(--gray-700)}
tbody tr:hover{background:var(--gray-50)}
tfoot td{font-weight:700;color:var(--gray-900);background:var(--gray-50);border-top:2px solid var(--gray-300);font-size:.8rem}

/* BADGES */
.badge{display:inline-block;padding:.15rem .5rem;border-radius:3px;font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.badge-pago{background:var(--green-light);color:var(--green)}
.badge-pendente{background:var(--red-light);color:var(--red)}
.badge-parcial{background:var(--blue-light);color:var(--blue)}
.badge-local{background:var(--amber-light);color:var(--amber)}
.badge-ind{background:var(--ind-light);color:var(--ind)}

/* EMPTY */
.empty{padding:2rem;text-align:center;color:var(--gray-500);font-size:.85rem;background:var(--gray-50);border-radius:6px}

/* FOOTER */
.footer{margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--gray-200);font-size:.7rem;color:var(--gray-500);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem}

/* BOTÕES FIXOS */
.actions{position:fixed;top:1rem;right:1rem;display:flex;gap:.5rem;z-index:100}
.btn{padding:.5rem 1rem;border:1px solid var(--gray-300);border-radius:6px;background:#fff;color:var(--gray-700);font-family:inherit;font-size:.78rem;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:.4rem;transition:all .15s}
.btn:hover{background:var(--gray-50);border-color:var(--gray-500)}
.btn-primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn-primary:hover{background:var(--primary-light);border-color:var(--primary-light)}

/* RESUMO EXTRATO */
.extrato-table td.desc{color:var(--gray-700)}
.extrato-table td.val{text-align:right;font-family:monospace;font-weight:600}
.extrato-table tr.neg td.val{color:var(--red)}
.extrato-table tr.pos td.val{color:var(--green)}
.extrato-table tr.total-row td{font-weight:700;background:var(--gray-50);border-top:2px solid var(--gray-300)}
.extrato-table tr.highlight td{background:var(--amber-light);font-weight:700;border-top:2px solid var(--primary)}

@media print{
  .actions{display:none}
  body{font-size:11px}
  .report{padding:0;max-width:100%}
  .tab-panel{display:block!important;margin-bottom:1.5rem;page-break-inside:avoid}
  .tabs{display:none}
  .identification{background:var(--primary)!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .kpi,th,.badge{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
</style>
</head>
<body>

<div class="actions">
  <button class="btn" onclick="window.print()">Imprimir</button>
  <button class="btn btn-primary" onclick="window.close()">Fechar</button>
</div>

<div class="report">

  <!-- HEADER -->
  <div class="header">
    <div class="brand">
      <div class="brand-name">{{ r.config.nome_empresa or 'COOPERATIVA AGRÍCOLA COPAR' }}</div>
      <div class="brand-sub">Relatório de Movimentação de Produtor</div>
      <div class="brand-info">
        <span>CNPJ:</span> {{ r.config.cnpj_empresa or '---' }}<br>
        <span>Endereço:</span> {{ r.config.endereco_empresa or '---' }}<br>
        <span>Telefone:</span> {{ r.config.telefone_empresa or '---' }}
      </div>
    </div>
    <div class="report-meta">
      <div class="report-title">Relatório Individual</div>
      <div style="margin-bottom:.4rem;">Emitido em</div>
      <div style="font-weight:600;color:var(--gray-900);margin-bottom:.5rem;">{{ r.data_geracao }}</div>
      <div class="report-id">REF: PRD-{{ '%06d' % r.produtor.id }}</div>
    </div>
  </div>

  <!-- IDENTIFICAÇÃO -->
  <div class="identification">
    <h2>Identificação do Produtor</h2>
    <div class="id-grid">
      <div class="id-item">
        <div class="label">Nome</div>
        <div class="value">{{ r.produtor.nome }}</div>
      </div>
      <div class="id-item">
        <div class="label">Matrícula</div>
        <div class="value mono">{{ r.produtor.matricula }}</div>
      </div>
      <div class="id-item">
        <div class="label">CPF</div>
        <div class="value mono">{{ r.produtor.cpf or '---' }}</div>
      </div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="kpi-grid">
    <div class="kpi green">
      <div class="label">Total Bruto Vendido</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_vendas_bruto)|replace('.', ',') }}</div>
      <div class="sub">{{ r.resumo.qtd_vendas }} venda(s)</div>
    </div>
    <div class="kpi amber">
      <div class="label">Comissão COPAR Paga</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_comissao_produtor)|replace('.', ',') }}</div>
      <div class="sub">R$ {{ '%.2f'|format(r.config.get('comissao_por_kg', 0.30)|float)|replace('.', ',') }}/kg</div>
    </div>
    <div class="kpi blue">
      <div class="label">Líquido Devido</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_liquido)|replace('.', ',') }}</div>
      <div class="sub">Após comissão e descontos</div>
    </div>
    <div class="kpi green">
      <div class="label">Total Recebido</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</div>
      <div class="sub">{{ r.resumo.qtd_pagamentos }} pagamento(s)</div>
    </div>
    <div class="kpi red">
      <div class="label">Saldo a Receber</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</div>
      <div class="sub">Pendente</div>
    </div>
    <div class="kpi">
      <div class="label">Estoque Atual</div>
      <div class="value">{{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</div>
      <div class="sub">{{ '%.3f'|format(r.resumo.total_kg_industria_estoque)|replace('.', ',') }} kg indústria</div>
    </div>
    <div class="kpi">
      <div class="label">Total Vendido</div>
      <div class="value">{{ '%.3f'|format(r.resumo.total_kg_vendido)|replace('.', ',') }} kg</div>
      <div class="sub">Histórico</div>
    </div>
    <div class="kpi ind">
      <div class="label">Horas de Banca</div>
      <div class="value">{{ '%.2f'|format(r.resumo.total_horas_banca) }} h</div>
      <div class="sub">{{ r.resumo.qtd_horas_registros }} registro(s)</div>
    </div>
  </div>

  <!-- TABS -->
  <div class="tabs">
    <button class="tab active" data-tab="estoque">Estoque Atual</button>
    <button class="tab" data-tab="vendas">Histórico de Vendas</button>
    <button class="tab" data-tab="pagamentos">Pagamentos</button>
    <button class="tab" data-tab="horas">Horas de Banca</button>
    <button class="tab" data-tab="comissoes">Comissões COPAR</button>
    <button class="tab" data-tab="extrato">Extrato Financeiro</button>
  </div>

  <!-- ══ TAB: ESTOQUE ══ -->
  <div class="tab-panel active" id="tab-estoque">
    <div class="section">
      <div class="section-title">
        <span>Estoque por Local, Variedade e Classe</span>
        <span class="section-total">Total: {{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</span>
      </div>
      {% if r.estoque %}
      <table>
        <thead>
          <tr>
            <th>Local</th>
            <th>Variedade</th>
            <th>Classe</th>
            <th class="num">Peso (kg)</th>
          </tr>
        </thead>
        <tbody>
          {% for e in r.estoque %}
          <tr>
            <td><span class="badge badge-local">{{ e.local }}</span></td>
            <td>{{ e.tipo }}</td>
            <td>{{ e.classe }}</td>
            <td class="num">{{ '%.3f'|format(e.peso)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3">Subtotal (sem indústria)</td>
            <td class="num">{{ '%.3f'|format(r.estoque|sum(attribute='peso'))|replace('.', ',') }} kg</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhum item em estoque comum.</div>
      {% endif %}
    </div>

    <div class="section" style="margin-top:2rem">
      <div class="section-title">
        <span>Estoque de Indústria (por Classe de Origem)</span>
        {% if r.estoque_industria %}
        <span class="section-total">{{ '%.3f'|format(r.resumo.total_kg_industria_estoque)|replace('.', ',') }} kg</span>
        {% endif %}
      </div>
      {% if r.estoque_industria %}
      <table>
        <thead>
          <tr>
            <th>Local</th>
            <th>Variedade</th>
            <th>Origem</th>
            <th class="num">Peso (kg)</th>
          </tr>
        </thead>
        <tbody>
          {% for e in r.estoque_industria %}
          <tr>
            <td><span class="badge badge-local">{{ e.local }}</span></td>
            <td>{{ e.tipo }}</td>
            <td><span class="badge badge-ind">{{ e.classe }}</span></td>
            <td class="num">{{ '%.3f'|format(e.peso)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3">TOTAL INDÚSTRIA</td>
            <td class="num">{{ '%.3f'|format(r.resumo.total_kg_industria_estoque)|replace('.', ',') }} kg</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhum estoque de indústria.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: VENDAS ══ -->
  <div class="tab-panel" id="tab-vendas">
    <div class="section">
      <div class="section-title">
        <span>Histórico Completo de Vendas</span>
        {% if r.vendas %}<span class="section-total">{{ r.resumo.qtd_vendas }} venda(s)</span>{% endif %}
      </div>
      {% if r.vendas %}
      <table>
        <thead>
          <tr>
            <th>Nº</th>
            <th>Data</th>
            <th>Produto</th>
            <th>Origem</th>
            <th class="num">Peso (kg)</th>
            <th class="num">R$/kg</th>
            <th class="num">Bruto</th>
            <th class="num">COPAR</th>
            <th class="num">Extras</th>
            <th class="num">Líquido</th>
            <th>Status</th>
            <th class="num">Saldo</th>
          </tr>
        </thead>
        <tbody>
          {% for v in r.vendas %}
          <tr>
            <td class="num">{{ '%05d' % v.id }}</td>
            <td>{{ v.data }}</td>
            <td>
              {% if v.is_industria %}
                <span class="badge badge-ind">{{ v.classe }}</span>
              {% else %}
                <strong>{{ v.tipo }}</strong> / {{ v.classe }}
              {% endif %}
            </td>
            <td>{{ v.origem }}</td>
            <td class="num">{{ '%.3f'|format(v.peso)|replace('.', ',') }}</td>
            <td class="num">{{ '%.2f'|format(v.valor_kg)|replace('.', ',') }}</td>
            <td class="num">{{ '%.2f'|format(v.valor_total)|replace('.', ',') }}</td>
            <td class="num" style="color:#92400e">-{{ '%.2f'|format(v.comissao)|replace('.', ',') }}</td>
            <td class="num" style="color:#6b7280">{{ '%.2f'|format(v.extra)|replace('.', ',') if v.extra > 0 else '—' }}</td>
            <td class="num"><strong>{{ '%.2f'|format(v.liquido)|replace('.', ',') }}</strong></td>
            <td>
              {% if v.status == 'Pago' %}<span class="badge badge-pago">Pago</span>
              {% elif v.status == 'Parcial' %}<span class="badge badge-parcial">Parcial</span>
              {% else %}<span class="badge badge-pendente">{{ v.status }}</span>{% endif %}
            </td>
            <td class="num">{{ '%.2f'|format(v.saldo)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="4">TOTAIS</td>
            <td class="num">{{ '%.3f'|format(r.resumo.total_kg_vendido)|replace('.', ',') }} kg</td>
            <td></td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_vendas_bruto)|replace('.', ',') }}</td>
            <td class="num">-R$ {{ '%.2f'|format(r.resumo.total_comissoes)|replace('.', ',') }}</td>
            <td class="num">-R$ {{ '%.2f'|format(r.resumo.total_extras)|replace('.', ',') }}</td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_liquido)|replace('.', ',') }}</td>
            <td></td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhuma venda registrada.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: PAGAMENTOS ══ -->
  <div class="tab-panel" id="tab-pagamentos">
    <div class="section">
      <div class="section-title">
        <span>Histórico de Pagamentos</span>
        {% if r.pagamentos %}<span class="section-total">Total: R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</span>{% endif %}
      </div>
      {% if r.pagamentos %}
      <table>
        <thead>
          <tr>
            <th>Nº Recibo</th>
            <th>Data / Hora</th>
            <th>Forma</th>
            <th>Observação</th>
            <th class="num">Valor</th>
          </tr>
        </thead>
        <tbody>
          {% for p in r.pagamentos %}
          <tr>
            <td class="num">REC-{{ '%05d' % p.id }}</td>
            <td>{{ p.data }}</td>
            <td>{{ p.forma }}</td>
            <td>{{ p.obs or '---' }}</td>
            <td class="num"><strong>R$ {{ '%.2f'|format(p.valor)|replace('.', ',') }}</strong></td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="4">TOTAL PAGO</td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhum pagamento registrado.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: HORAS DE BANCA ══ -->
  <div class="tab-panel" id="tab-horas">
    <div class="section">
      <div class="section-title">
        <span>Registros de Horas de Banca</span>
        {% if r.registros_horas_banca %}
        <span class="section-total">{{ '%.2f'|format(r.resumo.total_horas_banca) }} h totais</span>
        {% endif %}
      </div>
      {% if r.registros_horas_banca %}
      <table>
        <thead>
          <tr>
            <th>Nº</th>
            <th>Data</th>
            <th>Variedade</th>
            <th>Origem</th>
            <th>Destino</th>
            <th>Operador</th>
            <th class="num">Horas</th>
            <th class="num">Valor (R$)</th>
          </tr>
        </thead>
        <tbody>
          {% set valor_hora = r.config.get('valor_hora_banca', '16.00')|float %}
          {% for h in r.registros_horas_banca %}
          <tr>
            <td class="num">HB-{{ '%04d' % h.id }}</td>
            <td>{{ h.data }}</td>
            <td>{{ h.tipo }}</td>
            <td>{{ h.origem }}</td>
            <td>{{ h.destino }}</td>
            <td>{{ h.operador or '---' }}</td>
            <td class="num"><strong>{{ '%.2f'|format(h.horas) }}</strong></td>
            <td class="num">R$ {{ '%.2f'|format(h.horas * valor_hora)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="6">TOTAIS</td>
            <td class="num">{{ '%.2f'|format(r.resumo.total_horas_banca) }} h</td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_horas_banca * valor_hora)|replace('.', ',') }}</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhum registro de horas de banca.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: COMISSÕES ══ -->
  <div class="tab-panel" id="tab-comissoes">
    <div class="section">
      <div class="section-title">
        <span>Comissões COPAR Pagas pelo Produtor</span>
        {% if r.comissoes %}
        <span class="section-total">Total: R$ {{ '%.2f'|format(r.resumo.total_comissao_produtor)|replace('.', ',') }}</span>
        {% endif %}
      </div>
      {% if r.comissoes %}
      <table>
        <thead>
          <tr>
            <th>Nº</th>
            <th>Data</th>
            <th>Venda Ref.</th>
            <th>Descrição</th>
            <th class="num">Peso (kg)</th>
            <th class="num">Valor Comissão</th>
          </tr>
        </thead>
        <tbody>
          {% for c in r.comissoes %}
          <tr>
            <td class="num">CC-{{ '%05d' % c.id }}</td>
            <td>{{ c.data }}</td>
            <td class="num">{{ '#%05d' % c.venda_id if c.venda_id else '---' }}</td>
            <td>{{ c.descricao or '---' }}</td>
            <td class="num">{{ '%.3f'|format(c.peso)|replace('.', ',') }}</td>
            <td class="num"><strong>R$ {{ '%.2f'|format(c.valor)|replace('.', ',') }}</strong></td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="4">TOTAL DE COMISSÕES</td>
            <td class="num">
              {{ '%.3f'|format(r.comissoes|sum(attribute='peso'))|replace('.', ',') }} kg
            </td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_comissao_produtor)|replace('.', ',') }}</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhuma comissão COPAR registrada.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: EXTRATO ══ -->
  <div class="tab-panel" id="tab-extrato">
    <div class="section">
      <div class="section-title">
        <span>Extrato Financeiro Consolidado</span>
      </div>
      <table class="extrato-table">
        <tbody>
          <tr class="pos">
            <td class="desc">Total Bruto de Vendas</td>
            <td class="val">R$ {{ '%.2f'|format(r.resumo.total_vendas_bruto)|replace('.', ',') }}</td>
          </tr>
          <tr class="neg">
            <td class="desc">(-) Comissão COPAR</td>
            <td class="val">- R$ {{ '%.2f'|format(r.resumo.total_comissoes)|replace('.', ',') }}</td>
          </tr>
          <tr class="neg">
            <td class="desc">(-) Descontos Extras</td>
            <td class="val">- R$ {{ '%.2f'|format(r.resumo.total_extras)|replace('.', ',') }}</td>
          </tr>
          <tr class="total-row">
            <td class="desc">Líquido Devido ao Produtor</td>
            <td class="val">R$ {{ '%.2f'|format(r.resumo.total_liquido)|replace('.', ',') }}</td>
          </tr>
          <tr class="pos">
            <td class="desc">(+) Total Recebido</td>
            <td class="val">- R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</td>
          </tr>
          <tr class="highlight">
            <td class="desc">SALDO A RECEBER</td>
            <td class="val">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="section" style="margin-top:2rem">
      <div class="section-title">Posição de Estoque</div>
      <table class="extrato-table">
        <tbody>
          <tr>
            <td class="desc">Total Vendido (histórico)</td>
            <td class="val">{{ '%.3f'|format(r.resumo.total_kg_vendido)|replace('.', ',') }} kg</td>
          </tr>
          <tr>
            <td class="desc">Total em Estoque</td>
            <td class="val">{{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</td>
          </tr>
          <tr>
            <td class="desc">Horas de Banca Registradas</td>
            <td class="val">{{ '%.2f'|format(r.resumo.total_horas_banca) }} h</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <div>
      <strong>{{ r.config.nome_empresa or 'COPAR' }}</strong> &mdash;
      Documento gerado automaticamente pelo sistema COPAR Web
    </div>
    <div>{{ r.data_geracao }} &mdash; REF PRD-{{ '%06d' % r.produtor.id }}</div>
  </div>

</div>

<script>
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════════════════

def registrar_rotas_relatorios(app):

    @app.route('/gerente/relatorio/<int:produtor_id>')
    def gerente_relatorio_produtor(produtor_id):
        if not verificar_acesso_gerente():
            return redirect(url_for('login'))
        r = obter_relatorio_produtor_completo(produtor_id)
        if not r:
            return "Produtor não encontrado", 404
        return render_template_string(HTML_RELATORIO, r=r)

    print("✅ Módulo de Relatórios Empresariais ativado!")
