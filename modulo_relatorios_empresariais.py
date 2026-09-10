# -*- coding: utf-8 -*-
"""
MÓDULO DE RELATÓRIOS EMPRESARIAIS
Layout profissional sem emojis, com abas completas
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

def obter_configuracoes():
    conn = conectar_banco()
    if not conn: return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT chave, valor FROM configuracoes")
        config = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
        conn.close()
        return config
    except: return {}

def listar_descontos_ativos():
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT nome, tipo, valor FROM descontos_config 
            WHERE ativo = TRUE ORDER BY ordem, id
        """)
        d = [{'nome': r[0], 'tipo': r[1], 'valor': float(r[2])} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return d
    except: return []

def obter_relatorio_produtor_completo(produtor_id):
    """Relatório empresarial completo do produtor"""
    conn = conectar_banco()
    if not conn: return None
    try:
        cur = conn.cursor()
        
        # Dados do produtor
        cur.execute("""
            SELECT id, nome, matricula, COALESCE(cpf, '') 
            FROM produtores WHERE id = %s
        """, (produtor_id,))
        p = cur.fetchone()
        if not p:
            return None
        
        produtor = {'id': p[0], 'nome': p[1], 'matricula': p[2], 'cpf': p[3]}
        
        # 1. ESTOQUE ATUAL (detalhado)
        cur.execute("""
            SELECT local_estoque, tipo_alho, classe, 
                   SUM(peso) as total_peso,
                   COALESCE(SUM(horas_banca), 0) as horas
            FROM estoque
            WHERE produtor_id = %s AND peso > 0
            GROUP BY local_estoque, tipo_alho, classe
            ORDER BY local_estoque, tipo_alho, classe
        """, (produtor_id,))
        estoque = [{
            'local': r[0], 'tipo': r[1], 'classe': r[2],
            'peso': float(r[3]), 'horas': float(r[4])
        } for r in cur.fetchall()]
        
        # 2. VENDAS DETALHADAS
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_kg, v.valor_total, v.valor_produtor, 
                   v.desconto_comissao, v.status_pagamento, v.origem_estoque,
                   COALESCE(cp.saldo, v.valor_produtor) as saldo,
                   COALESCE(cp.valor_pago, 0) as pago,
                   v.comprador
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
                'data_iso': r[1].isoformat() if r[1] else '',
                'tipo': r[2], 'classe': r[3],
                'peso': float(r[4]),
                'valor_kg': float(r[5] or 0),
                'valor_total': float(r[6] or 0),
                'valor_produtor': float(r[7] or 0),
                'comissao': float(r[8] or 0),
                'status': r[9],
                'origem': r[10] or '',
                'saldo': float(r[11] or 0),
                'pago': float(r[12] or 0),
                'comprador': r[13] or ''
            })
        
        # 3. PAGAMENTOS
        cur.execute("""
            SELECT id, data_pagamento, valor_total, forma_pagamento, observacoes
            FROM pagamentos
            WHERE produtor_id = %s
            ORDER BY data_pagamento DESC
        """, (produtor_id,))
        pagamentos = [{
            'id': r[0],
            'data': r[1].strftime("%d/%m/%Y %H:%M") if r[1] else '',
            'data_iso': r[1].isoformat() if r[1] else '',
            'valor': float(r[2]),
            'forma': r[3],
            'obs': r[4] or ''
        } for r in cur.fetchall()]
        
        # 4. HORAS DE BANCA TOTAIS (histórico - soma tudo)
        cur.execute("""
            SELECT COALESCE(SUM(horas_banca), 0) FROM estoque WHERE produtor_id = %s
        """, (produtor_id,))
        horas_estoque = float(cur.fetchone()[0])
        
        # 5. RESUMO FINANCEIRO
        total_vendas_bruto = sum(v['valor_total'] for v in vendas)
        total_comissoes = sum(v['comissao'] for v in vendas)
        total_liquido_produtor = sum(v['valor_produtor'] for v in vendas)
        total_pago = sum(p['valor'] for p in pagamentos)
        total_pendente = sum(v['saldo'] for v in vendas if v['saldo'] > 0)
        total_kg_vendido = sum(v['peso'] for v in vendas)
        total_kg_estoque = sum(e['peso'] for e in estoque)
        
        cur.close()
        conn.close()
        
        return {
            'produtor': produtor,
            'estoque': estoque,
            'vendas': vendas,
            'pagamentos': pagamentos,
            'config': obter_configuracoes(),
            'descontos': listar_descontos_ativos(),
            'resumo': {
                'total_vendas_bruto': total_vendas_bruto,
                'total_comissoes': total_comissoes,
                'total_liquido_produtor': total_liquido_produtor,
                'total_pago': total_pago,
                'total_pendente': total_pendente,
                'total_kg_vendido': total_kg_vendido,
                'total_kg_estoque': total_kg_estoque,
                'horas_banca_estoque': horas_estoque,
                'qtd_vendas': len(vendas),
                'qtd_pagamentos': len(pagamentos)
            },
            'data_geracao': datetime.now().strftime("%d/%m/%Y às %H:%M")
        }
    except Exception as e:
        logger.error(f"Erro relatorio produtor: {e}")
        return None


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
}
body{font-family:'Inter',sans-serif;background:#fff;color:var(--gray-900);font-size:13px;line-height:1.5}

.report{max-width:1000px;margin:0 auto;padding:2rem}

/* HEADER EMPRESARIAL */
.header{
  border-bottom:3px solid var(--primary);
  padding-bottom:1.5rem;margin-bottom:2rem;
  display:flex;justify-content:space-between;align-items:flex-start;
  gap:2rem;flex-wrap:wrap;
}
.brand{flex:1;min-width:280px}
.brand-name{
  font-size:1.6rem;font-weight:800;color:var(--primary);
  letter-spacing:-.02em;margin-bottom:.25rem;
}
.brand-sub{font-size:.75rem;color:var(--gray-500);font-weight:500;text-transform:uppercase;letter-spacing:.1em}
.brand-info{margin-top:.75rem;font-size:.8rem;color:var(--gray-700);line-height:1.7}
.brand-info span{color:var(--gray-500)}

.report-meta{text-align:right;font-size:.78rem;color:var(--gray-500);min-width:200px}
.report-title{
  font-size:1rem;font-weight:700;color:var(--gray-900);
  margin-bottom:.5rem;text-transform:uppercase;letter-spacing:.08em;
}
.report-id{
  display:inline-block;background:var(--gray-100);padding:.2rem .6rem;
  border-radius:4px;font-family:monospace;font-size:.72rem;color:var(--gray-700);
}

/* IDENTIFICAÇÃO */
.identification{
  background:linear-gradient(135deg,var(--primary) 0%,var(--primary-light) 100%);
  color:#fff;padding:1.5rem;border-radius:8px;margin-bottom:2rem;
}
.identification h2{
  font-size:.7rem;text-transform:uppercase;letter-spacing:.15em;
  opacity:.75;margin-bottom:.75rem;font-weight:600;
}
.id-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1.5rem}
.id-item .label{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;opacity:.7;margin-bottom:.25rem}
.id-item .value{font-size:1.05rem;font-weight:600}
.id-item .value.mono{font-family:monospace;letter-spacing:.02em}

/* KPIs */
.kpi-grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:1rem;margin-bottom:2rem;
}
.kpi{
  border:1px solid var(--gray-200);border-radius:6px;padding:1rem 1.15rem;
  border-left:3px solid var(--primary);
}
.kpi.green{border-left-color:var(--green)}
.kpi.amber{border-left-color:var(--amber)}
.kpi.red{border-left-color:var(--red)}
.kpi.blue{border-left-color:var(--blue)}
.kpi .label{
  font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--gray-500);font-weight:600;margin-bottom:.4rem;
}
.kpi .value{font-size:1.35rem;font-weight:700;font-family:monospace;color:var(--gray-900);letter-spacing:-.02em}
.kpi .sub{font-size:.7rem;color:var(--gray-500);margin-top:.2rem}

/* TABS */
.tabs{
  display:flex;gap:0;border-bottom:2px solid var(--gray-200);
  margin-bottom:1.5rem;overflow-x:auto;
}
.tab{
  padding:.75rem 1.25rem;background:none;border:none;cursor:pointer;
  font-family:inherit;font-size:.8rem;font-weight:600;color:var(--gray-500);
  text-transform:uppercase;letter-spacing:.06em;
  border-bottom:2px solid transparent;margin-bottom:-2px;
  transition:all .2s;white-space:nowrap;
}
.tab:hover{color:var(--primary)}
.tab.active{color:var(--primary);border-bottom-color:var(--primary)}

.tab-panel{display:none;animation:fadeIn .2s ease}
.tab-panel.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}

/* SECTION */
.section{margin-bottom:2rem}
.section-title{
  font-size:.75rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:var(--primary);margin-bottom:.75rem;
  padding-bottom:.4rem;border-bottom:1px solid var(--gray-200);
  display:flex;justify-content:space-between;align-items:center;
}
.section-total{font-family:monospace;color:var(--gray-700);font-weight:600}

/* TABELAS */
table{width:100%;border-collapse:collapse;font-size:.8rem;background:#fff}
thead{background:var(--gray-50)}
th{
  text-align:left;padding:.6rem .75rem;font-size:.68rem;font-weight:700;
  color:var(--gray-500);text-transform:uppercase;letter-spacing:.06em;
  border-bottom:1px solid var(--gray-300);white-space:nowrap;
}
th.num,td.num{text-align:right;font-family:monospace}
td{padding:.6rem .75rem;border-bottom:1px solid var(--gray-100);color:var(--gray-700)}
tbody tr:hover{background:var(--gray-50)}
tfoot td{
  font-weight:700;color:var(--gray-900);background:var(--gray-50);
  border-top:2px solid var(--gray-300);font-size:.82rem;
}

/* BADGES */
.badge{
  display:inline-block;padding:.15rem .5rem;border-radius:3px;
  font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
}
.badge-pago{background:var(--green-light);color:var(--green)}
.badge-pendente{background:var(--red-light);color:var(--red)}
.badge-parcial{background:var(--blue-light);color:var(--blue)}
.badge-local{background:var(--amber-light);color:var(--amber)}

/* EMPTY */
.empty{padding:2rem;text-align:center;color:var(--gray-500);font-size:.85rem;background:var(--gray-50);border-radius:6px}

/* FOOTER */
.footer{
  margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--gray-200);
  font-size:.72rem;color:var(--gray-500);
  display:flex;justify-content:space-between;align-items:center;
  flex-wrap:wrap;gap:1rem;
}

/* BOTÕES */
.actions{
  position:fixed;top:1rem;right:1rem;display:flex;gap:.5rem;z-index:100;
}
.btn{
  padding:.5rem 1rem;border:1px solid var(--gray-300);border-radius:6px;
  background:#fff;color:var(--gray-700);font-family:inherit;font-size:.78rem;
  font-weight:600;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:.4rem;transition:all .15s;
}
.btn:hover{background:var(--gray-50);border-color:var(--gray-500)}
.btn-primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn-primary:hover{background:var(--primary-light);border-color:var(--primary-light)}

/* DESCONTOS INFO */
.discount-box{
  background:var(--gray-50);border-left:3px solid var(--accent);
  padding:1rem 1.15rem;border-radius:4px;margin-bottom:1rem;
}
.discount-title{
  font-size:.7rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:var(--gray-700);margin-bottom:.5rem;
}
.discount-list{display:grid;gap:.35rem}
.discount-item{
  display:flex;justify-content:space-between;font-size:.78rem;
  color:var(--gray-700);
}
.discount-item .val{font-family:monospace;font-weight:600}

@media print{
  .actions{display:none}
  body{font-size:11px}
  .report{padding:0;max-width:100%}
  .tab-panel{display:block!important;page-break-inside:avoid;margin-bottom:1.5rem}
  .tab-panel:not(.active){display:block!important}
  .tabs{display:none}
  .identification{background:var(--primary)!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .kpi{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  th{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .badge{-webkit-print-color-adjust:exact;print-color-adjust:exact}
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

  <!-- IDENTIFICAÇÃO DO PRODUTOR -->
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
      <div class="sub">{{ r.resumo.qtd_vendas }} venda(s) registrada(s)</div>
    </div>
    <div class="kpi amber">
      <div class="label">Comissões / Descontos</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_comissoes)|replace('.', ',') }}</div>
      <div class="sub">Sobre vendas realizadas</div>
    </div>
    <div class="kpi blue">
      <div class="label">Líquido ao Produtor</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_liquido_produtor)|replace('.', ',') }}</div>
      <div class="sub">Após descontos</div>
    </div>
    <div class="kpi green">
      <div class="label">Total Recebido</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</div>
      <div class="sub">{{ r.resumo.qtd_pagamentos }} pagamento(s)</div>
    </div>
    <div class="kpi red">
      <div class="label">Saldo Pendente</div>
      <div class="value">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</div>
      <div class="sub">A receber</div>
    </div>
    <div class="kpi">
      <div class="label">Estoque Atual</div>
      <div class="value">{{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</div>
      <div class="sub">Alho em estoque</div>
    </div>
    <div class="kpi">
      <div class="label">Total Vendido</div>
      <div class="value">{{ '%.3f'|format(r.resumo.total_kg_vendido)|replace('.', ',') }} kg</div>
      <div class="sub">Quantidade vendida</div>
    </div>
    <div class="kpi amber">
      <div class="label">Horas de Banca</div>
      <div class="value">{{ '%.1f'|format(r.resumo.horas_banca_estoque) }} h</div>
      <div class="sub">Em estoque atual</div>
    </div>
  </div>

  <!-- TABS -->
  <div class="tabs">
    <button class="tab active" data-tab="estoque">Estoque Atual</button>
    <button class="tab" data-tab="vendas">Histórico de Vendas</button>
    <button class="tab" data-tab="pagamentos">Pagamentos</button>
    <button class="tab" data-tab="descontos">Descontos Aplicados</button>
    <button class="tab" data-tab="extrato">Extrato Financeiro</button>
  </div>

  <!-- ══ TAB: ESTOQUE ══ -->
  <div class="tab-panel active" id="tab-estoque">
    <div class="section">
      <div class="section-title">
        <span>Estoque Atual por Local, Variedade e Classe</span>
        {% if r.estoque %}
        <span class="section-total">Total: {{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</span>
        {% endif %}
      </div>
      {% if r.estoque %}
      <table>
        <thead>
          <tr>
            <th>Local</th>
            <th>Variedade</th>
            <th>Classe</th>
            <th class="num">Peso (kg)</th>
            <th class="num">Horas Banca</th>
          </tr>
        </thead>
        <tbody>
          {% for e in r.estoque %}
          <tr>
            <td><span class="badge badge-local">{{ e.local }}</span></td>
            <td>{{ e.tipo }}</td>
            <td>{{ e.classe }}</td>
            <td class="num">{{ '%.3f'|format(e.peso)|replace('.', ',') }}</td>
            <td class="num">{{ '%.1f'|format(e.horas) }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3">TOTAL EM ESTOQUE</td>
            <td class="num">{{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</td>
            <td class="num">{{ '%.1f'|format(r.resumo.horas_banca_estoque) }} h</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhum item em estoque no momento.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: VENDAS ══ -->
  <div class="tab-panel" id="tab-vendas">
    <div class="section">
      <div class="section-title">
        <span>Histórico Completo de Vendas</span>
        {% if r.vendas %}
        <span class="section-total">{{ r.resumo.qtd_vendas }} venda(s)</span>
        {% endif %}
      </div>
      {% if r.vendas %}
      <table>
        <thead>
          <tr>
            <th>Nº</th>
            <th>Data</th>
            <th>Variedade / Classe</th>
            <th>Origem</th>
            <th class="num">Peso (kg)</th>
            <th class="num">R$/kg</th>
            <th class="num">Bruto</th>
            <th class="num">Desconto</th>
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
            <td><strong>{{ v.tipo }}</strong> / {{ v.classe }}</td>
            <td>{{ v.origem }}</td>
            <td class="num">{{ '%.3f'|format(v.peso)|replace('.', ',') }}</td>
            <td class="num">{{ '%.2f'|format(v.valor_kg)|replace('.', ',') }}</td>
            <td class="num">{{ '%.2f'|format(v.valor_total)|replace('.', ',') }}</td>
            <td class="num">-{{ '%.2f'|format(v.comissao)|replace('.', ',') }}</td>
            <td class="num"><strong>{{ '%.2f'|format(v.valor_produtor)|replace('.', ',') }}</strong></td>
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
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_liquido_produtor)|replace('.', ',') }}</td>
            <td></td>
            <td class="num">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</td>
          </tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Nenhuma venda registrada até o momento.</div>
      {% endif %}
    </div>
  </div>

  <!-- ══ TAB: PAGAMENTOS ══ -->
  <div class="tab-panel" id="tab-pagamentos">
    <div class="section">
      <div class="section-title">
        <span>Histórico de Pagamentos</span>
        {% if r.pagamentos %}
        <span class="section-total">Total: R$ {{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</span>
        {% endif %}
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

  <!-- ══ TAB: DESCONTOS ══ -->
  <div class="tab-panel" id="tab-descontos">
    <div class="section">
      <div class="section-title">
        <span>Descontos Configurados (Aplicados sobre Vendas)</span>
      </div>
      {% if r.descontos %}
      <div class="discount-box">
        <div class="discount-title">Descontos Ativos</div>
        <div class="discount-list">
          {% for d in r.descontos %}
          <div class="discount-item">
            <span>{{ d.nome }}</span>
            <span class="val">
              {% if d.tipo == 'percentual' %}
                {{ '%.2f'|format(d.valor)|replace('.', ',') }} %
              {% else %}
                R$ {{ '%.2f'|format(d.valor)|replace('.', ',') }}
              {% endif %}
            </span>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}
      
      <div class="discount-box" style="border-left-color:var(--primary);margin-top:1.5rem">
        <div class="discount-title">Resumo de Descontos no Período</div>
        <div class="discount-list">
          <div class="discount-item">
            <span>Total Bruto Vendido</span>
            <span class="val">R$ {{ '%.2f'|format(r.resumo.total_vendas_bruto)|replace('.', ',') }}</span>
          </div>
          <div class="discount-item">
            <span>Total de Descontos Aplicados</span>
            <span class="val" style="color:var(--red)">- R$ {{ '%.2f'|format(r.resumo.total_comissoes)|replace('.', ',') }}</span>
          </div>
          <div class="discount-item" style="border-top:1px solid var(--gray-300);padding-top:.4rem;margin-top:.4rem;font-weight:700">
            <span>Valor Líquido ao Produtor</span>
            <span class="val" style="color:var(--green)">R$ {{ '%.2f'|format(r.resumo.total_liquido_produtor)|replace('.', ',') }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ TAB: EXTRATO ══ -->
  <div class="tab-panel" id="tab-extrato">
    <div class="section">
      <div class="section-title">
        <span>Extrato Financeiro Consolidado</span>
      </div>
      
      <table style="margin-bottom:1.5rem">
        <thead>
          <tr>
            <th style="width:60%">Descrição</th>
            <th class="num">Valor (R$)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Total Bruto de Vendas</td>
            <td class="num">{{ '%.2f'|format(r.resumo.total_vendas_bruto)|replace('.', ',') }}</td>
          </tr>
          <tr>
            <td>(-) Descontos e Comissões</td>
            <td class="num" style="color:var(--red)">-{{ '%.2f'|format(r.resumo.total_comissoes)|replace('.', ',') }}</td>
          </tr>
          <tr style="font-weight:700;background:var(--gray-50)">
            <td>Líquido Devido ao Produtor</td>
            <td class="num">{{ '%.2f'|format(r.resumo.total_liquido_produtor)|replace('.', ',') }}</td>
          </tr>
          <tr>
            <td>(+) Total Recebido</td>
            <td class="num" style="color:var(--green)">-{{ '%.2f'|format(r.resumo.total_pago)|replace('.', ',') }}</td>
          </tr>
          <tr style="font-weight:700;background:var(--amber-light)">
            <td>SALDO A RECEBER</td>
            <td class="num" style="color:var(--amber)">R$ {{ '%.2f'|format(r.resumo.total_pendente)|replace('.', ',') }}</td>
          </tr>
        </tbody>
      </table>

      <div class="section-title" style="margin-top:2rem">Posição de Estoque</div>
      <table>
        <thead>
          <tr><th style="width:60%">Descrição</th><th class="num">Quantidade</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Total Vendido (histórico)</td>
            <td class="num">{{ '%.3f'|format(r.resumo.total_kg_vendido)|replace('.', ',') }} kg</td>
          </tr>
          <tr>
            <td>Total em Estoque (atual)</td>
            <td class="num">{{ '%.3f'|format(r.resumo.total_kg_estoque)|replace('.', ',') }} kg</td>
          </tr>
          <tr>
            <td>Horas de Banca em Estoque</td>
            <td class="num">{{ '%.1f'|format(r.resumo.horas_banca_estoque) }} h</td>
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
    <div>
      {{ r.data_geracao }} &mdash; REF PRD-{{ '%06d' % r.produtor.id }}
    </div>
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


def registrar_rotas_relatorios(app):
    @app.route('/gerente/relatorio/<int:produtor_id>')
    def gerente_relatorio_produtor(produtor_id):
        if not verificar_acesso_gerente():
            return redirect(url_for('login'))
        r = obter_relatorio_produtor_completo(produtor_id)
        if not r:
            return "Produtor não encontrado", 404
        return render_template_string(HTML_RELATORIO, r=r)
    
    print("✅ Módulo de Relatórios Empresariais carregado!")
