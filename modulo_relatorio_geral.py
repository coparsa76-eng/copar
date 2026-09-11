# -*- coding: utf-8 -*-
"""
MÓDULO DE RELATÓRIO GERAL DA COPAR
- KPIs consolidados
- Caixa COPAR (total + por mês + movimentos)
- Estoque, vendas, top produtores, horas de banca
- Layout empresarial sem emojis
"""
from flask import render_template_string, jsonify, session, redirect, url_for
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
# DADOS DO RELATÓRIO GERAL
# ══════════════════════════════════════════════════════════════════════════

def obter_relatorio_geral_completo():
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()

        # ── Totais gerais ────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM produtores")
        total_produtores = cur.fetchone()[0]

        # Estoque total e por local
        cur.execute("""
            SELECT local_estoque, COALESCE(SUM(peso), 0)
            FROM estoque WHERE peso > 0
            GROUP BY local_estoque ORDER BY local_estoque
        """)
        estoque_por_local = {r[0]: float(r[1]) for r in cur.fetchall()}
        estoque_total = sum(estoque_por_local.values())

        # Estoque por tipo
        cur.execute("""
            SELECT tipo_alho, COALESCE(SUM(peso), 0)
            FROM estoque WHERE peso > 0
            GROUP BY tipo_alho ORDER BY SUM(peso) DESC
        """)
        estoque_por_tipo = {r[0] or 'Não definido': float(r[1]) for r in cur.fetchall()}

        # Estoque de indústria separado (por classe)
        cur.execute("""
            SELECT classe, COALESCE(SUM(peso), 0)
            FROM estoque
            WHERE peso > 0 AND classe LIKE 'Indústria%'
            GROUP BY classe ORDER BY classe
        """)
        estoque_industria = {r[0]: float(r[1]) for r in cur.fetchall()}
        total_industria = sum(estoque_industria.values())

        # ── Vendas ────────────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM vendas")
        total_vendas_qtd = cur.fetchone()[0]

        cur.execute("""
            SELECT COALESCE(SUM(peso), 0), COALESCE(SUM(valor_total), 0),
                   COALESCE(SUM(valor_produtor), 0),
                   COALESCE(SUM(desconto_comissao), 0),
                   COALESCE(SUM(desconto_extra), 0)
            FROM vendas
        """)
        r = cur.fetchone()
        total_vendido_kg = float(r[0])
        total_vendido_bruto = float(r[1])
        total_vendido_produtor = float(r[2])
        total_comissao_geral = float(r[3])
        total_descontos_extra = float(r[4])

        # Vendas por mês (últimos 12 meses)
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', data_venda), 'MM/YYYY') AS mes,
                   DATE_TRUNC('month', data_venda) AS ordenacao,
                   COUNT(*) AS qtd,
                   COALESCE(SUM(peso), 0) AS peso,
                   COALESCE(SUM(valor_total), 0) AS bruto,
                   COALESCE(SUM(desconto_comissao), 0) AS comissao,
                   COALESCE(SUM(valor_produtor), 0) AS liquido
            FROM vendas
            WHERE data_venda >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', data_venda)
            ORDER BY ordenacao DESC
        """)
        vendas_mensais = [{
            'mes': r[0],
            'qtd': r[2],
            'peso': float(r[3]),
            'bruto': float(r[4]),
            'comissao': float(r[5]),
            'liquido': float(r[6]),
        } for r in cur.fetchall()]

        # Top 10 produtores
        cur.execute("""
            SELECT p.nome, p.matricula,
                   COALESCE(SUM(v.peso), 0) AS peso,
                   COALESCE(SUM(v.valor_total), 0) AS valor,
                   COALESCE(SUM(v.desconto_comissao), 0) AS comissao
            FROM vendas v
            JOIN produtores p ON v.produtor_id = p.id
            GROUP BY p.id, p.nome, p.matricula
            ORDER BY peso DESC
            LIMIT 10
        """)
        top_produtores = [{
            'nome': r[0], 'matricula': r[1],
            'peso': float(r[2]), 'valor': float(r[3]),
            'comissao': float(r[4]),
        } for r in cur.fetchall()]

        # ── Pagamentos ────────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM pagamentos")
        total_pagamentos_qtd = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(valor_total), 0) FROM pagamentos")
        total_pago = float(cur.fetchone()[0])

        cur.execute("""
            SELECT COALESCE(SUM(valor_total), 0) FROM pagamentos
            WHERE EXTRACT(YEAR FROM data_pagamento) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND EXTRACT(MONTH FROM data_pagamento) = EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        pagamentos_mes = float(cur.fetchone()[0])

        # ── Horas de banca ────────────────────────────────────────────────
        cur.execute("SELECT COALESCE(SUM(horas), 0) FROM registros_horas_banca")
        total_horas_banca = float(cur.fetchone()[0])

        cur.execute("""
            SELECT COUNT(*) FROM registros_horas_banca
            WHERE EXTRACT(YEAR FROM registrado_em) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND EXTRACT(MONTH FROM registrado_em) = EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        registros_hb_mes = cur.fetchone()[0]

        cur.execute("""
            SELECT p.nome, p.matricula, COALESCE(SUM(h.horas), 0) AS total_h
            FROM produtores p
            JOIN registros_horas_banca h ON p.id = h.produtor_id
            GROUP BY p.id, p.nome, p.matricula
            ORDER BY total_h DESC
            LIMIT 10
        """)
        horas_por_produtor = [{
            'nome': r[0], 'matricula': r[1], 'horas': float(r[2]),
        } for r in cur.fetchall()]

        # ── CAIXA COPAR ───────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN valor ELSE 0 END), 0) AS comissao,
                COALESCE(SUM(CASE WHEN tipo_movimento = 'ajuste' THEN valor ELSE 0 END), 0) AS ajustes,
                COALESCE(SUM(CASE WHEN tipo_movimento = 'retirada' THEN valor ELSE 0 END), 0) AS retiradas,
                COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN peso_kg ELSE 0 END), 0) AS peso_comissao
            FROM caixa_copar
        """)
        cr = cur.fetchone()
        copar_comissao = float(cr[0])
        copar_ajustes = float(cr[1])
        copar_retiradas = float(cr[2])
        copar_peso = float(cr[3])
        copar_saldo = copar_comissao + copar_ajustes - copar_retiradas

        # Caixa COPAR por mês (últimos 12 meses)
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', data_movimento), 'MM/YYYY') AS mes,
                   DATE_TRUNC('month', data_movimento) AS ordenacao,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN valor ELSE 0 END), 0) AS comissao,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'ajuste' THEN valor ELSE 0 END), 0) AS ajustes,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'retirada' THEN valor ELSE 0 END), 0) AS retiradas,
                   COUNT(CASE WHEN tipo_movimento = 'comissao' THEN 1 END) AS qtd_vendas,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN peso_kg ELSE 0 END), 0) AS peso
            FROM caixa_copar
            WHERE data_movimento >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', data_movimento)
            ORDER BY ordenacao DESC
        """)
        copar_por_mes = [{
            'mes': r[0],
            'comissao': float(r[2]),
            'ajustes': float(r[3]),
            'retiradas': float(r[4]),
            'saldo_mes': float(r[2]) + float(r[3]) - float(r[4]),
            'qtd_vendas': r[5],
            'peso': float(r[6]),
        } for r in cur.fetchall()]

        # Últimos movimentos da caixa
        cur.execute("""
            SELECT c.id, c.data_movimento, c.tipo_movimento,
                   COALESCE(p.nome, '---') AS produtor_nome,
                   c.peso_kg, c.valor, c.descricao, c.venda_id
            FROM caixa_copar c
            LEFT JOIN produtores p ON c.produtor_id = p.id
            ORDER BY c.data_movimento DESC
            LIMIT 30
        """)
        copar_movimentos = [{
            'id': r[0],
            'data': r[1].strftime("%d/%m/%Y %H:%M") if r[1] else "",
            'tipo': r[2],
            'produtor': r[3],
            'peso': float(r[4]) if r[4] else 0,
            'valor': float(r[5]),
            'descricao': r[6] or "",
            'venda_id': r[7],
        } for r in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            'data_geracao': datetime.now().strftime("%d/%m/%Y às %H:%M"),
            'config': _obter_configuracoes(),
            'produtores': {
                'total': total_produtores,
            },
            'estoque': {
                'total_kg': estoque_total,
                'por_local': estoque_por_local,
                'por_tipo': estoque_por_tipo,
                'industria': estoque_industria,
                'total_industria': total_industria,
            },
            'vendas': {
                'qtd': total_vendas_qtd,
                'peso_total': total_vendido_kg,
                'bruto_total': total_vendido_bruto,
                'produtor_total': total_vendido_produtor,
                'comissao_total': total_comissao_geral,
                'descontos_extra_total': total_descontos_extra,
                'por_mes': vendas_mensais,
            },
            'pagamentos': {
                'qtd': total_pagamentos_qtd,
                'total': total_pago,
                'mes': pagamentos_mes,
            },
            'horas_banca': {
                'total': total_horas_banca,
                'registros_mes': registros_hb_mes,
                'por_produtor': horas_por_produtor,
            },
            'top_produtores': top_produtores,
            'caixa_copar': {
                'saldo_atual': round(copar_saldo, 2),
                'total_comissao': round(copar_comissao, 2),
                'total_ajustes': round(copar_ajustes, 2),
                'total_retiradas': round(copar_retiradas, 2),
                'peso_comissionado': round(copar_peso, 2),
                'por_mes': copar_por_mes,
                'movimentos': copar_movimentos,
            },
        }
    except Exception as e:
        logger.error(f"Erro relatorio geral: {e}")
        import traceback
        traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════════════
# HTML DO RELATÓRIO GERAL
# ══════════════════════════════════════════════════════════════════════════

HTML_RELATORIO_GERAL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Relatório Geral - COPAR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#0a3d2c;--primary-light:#1a6b4d;--accent:#b8935a;
  --gray-50:#f9fafb;--gray-100:#f3f4f6;--gray-200:#e5e7eb;--gray-300:#d1d5db;
  --gray-500:#6b7280;--gray-700:#374151;--gray-900:#111827;
  --red:#991b1b;--red-light:#fee2e2;--green:#166534;--green-light:#dcfce7;
  --amber:#92400e;--amber-light:#fef3c7;--blue:#1e40af;--blue-light:#dbeafe;
  --ind:#7c3aed;--ind-light:#ede9fe;
}
body{font-family:'Inter',sans-serif;background:#fff;color:var(--gray-900);font-size:13px;line-height:1.5}
.report{max-width:1150px;margin:0 auto;padding:2rem}

.header{border-bottom:3px solid var(--primary);padding-bottom:1.5rem;margin-bottom:2rem;display:flex;justify-content:space-between;align-items:flex-start;gap:2rem;flex-wrap:wrap}
.brand{flex:1;min-width:280px}
.brand-name{font-size:1.5rem;font-weight:800;color:var(--primary);letter-spacing:-.02em;margin-bottom:.25rem}
.brand-sub{font-size:.72rem;color:var(--gray-500);font-weight:500;text-transform:uppercase;letter-spacing:.12em}
.brand-info{margin-top:.75rem;font-size:.78rem;color:var(--gray-700);line-height:1.7}
.brand-info span{color:var(--gray-500)}
.report-meta{text-align:right;font-size:.75rem;color:var(--gray-500);min-width:200px}
.report-title{font-size:.95rem;font-weight:700;color:var(--gray-900);margin-bottom:.5rem;text-transform:uppercase;letter-spacing:.08em}
.report-id{display:inline-block;background:var(--gray-100);padding:.2rem .6rem;border-radius:4px;font-family:monospace;font-size:.72rem;color:var(--gray-700)}

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

/* CAIXA COPAR DESTAQUE */
.caixa-copar{
  background:linear-gradient(135deg,#0a3d2c 0%,#1a6b4d 100%);
  color:#fff;
  padding:1.75rem 2rem;
  border-radius:8px;
  margin-bottom:2rem;
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:2rem;
  flex-wrap:wrap;
}
.caixa-copar .titulo{
  font-size:.72rem;text-transform:uppercase;letter-spacing:.15em;
  opacity:.8;font-weight:600;margin-bottom:.5rem;
}
.caixa-copar .saldo{font-size:2.5rem;font-weight:800;font-family:monospace;letter-spacing:-.03em}
.caixa-copar .info{font-size:.8rem;opacity:.85;margin-top:.4rem}
.caixa-copar .stats{display:flex;gap:2rem;flex-wrap:wrap}
.caixa-copar .stat .lbl{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;opacity:.7;margin-bottom:.3rem}
.caixa-copar .stat .val{font-size:1.1rem;font-weight:700;font-family:monospace}

.section{margin-bottom:2rem}
.section-title{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--primary);margin-bottom:.75rem;padding-bottom:.4rem;border-bottom:1px solid var(--gray-200);display:flex;justify-content:space-between;align-items:center}
.section-total{font-family:monospace;color:var(--gray-700);font-weight:600}

table{width:100%;border-collapse:collapse;font-size:.78rem;background:#fff}
thead{background:var(--gray-50)}
th{text-align:left;padding:.6rem .75rem;font-size:.66rem;font-weight:700;color:var(--gray-500);text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--gray-300);white-space:nowrap}
th.num,td.num{text-align:right;font-family:monospace}
td{padding:.6rem .75rem;border-bottom:1px solid var(--gray-100);color:var(--gray-700)}
tbody tr:hover{background:var(--gray-50)}
tfoot td{font-weight:700;color:var(--gray-900);background:var(--gray-50);border-top:2px solid var(--gray-300);font-size:.8rem}

.badge{display:inline-block;padding:.15rem .5rem;border-radius:3px;font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.badge-comissao{background:var(--amber-light);color:var(--amber)}
.badge-ajuste{background:var(--blue-light);color:var(--blue)}
.badge-retirada{background:var(--red-light);color:var(--red)}
.badge-ind{background:var(--ind-light);color:var(--ind)}

.empty{padding:2rem;text-align:center;color:var(--gray-500);font-size:.85rem;background:var(--gray-50);border-radius:6px}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:2rem;margin-bottom:2rem}
@media(max-width:800px){.grid-2{grid-template-columns:1fr}}

.footer{margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--gray-200);font-size:.7rem;color:var(--gray-500);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem}

.actions{position:fixed;top:1rem;right:1rem;display:flex;gap:.5rem;z-index:100}
.btn{padding:.5rem 1rem;border:1px solid var(--gray-300);border-radius:6px;background:#fff;color:var(--gray-700);font-family:inherit;font-size:.78rem;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:.4rem;transition:all .15s}
.btn:hover{background:var(--gray-50);border-color:var(--gray-500)}
.btn-primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn-primary:hover{background:var(--primary-light);border-color:var(--primary-light)}

@media print{
  .actions{display:none}
  body{font-size:11px}
  .report{padding:0;max-width:100%}
  .caixa-copar{background:var(--primary)!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
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
      <div class="brand-sub">Relatório Gerencial Consolidado</div>
      <div class="brand-info">
        <span>CNPJ:</span> {{ r.config.cnpj_empresa or '---' }}<br>
        <span>Endereço:</span> {{ r.config.endereco_empresa or '---' }}<br>
        <span>Telefone:</span> {{ r.config.telefone_empresa or '---' }}
      </div>
    </div>
    <div class="report-meta">
      <div class="report-title">Relatório Geral</div>
      <div style="margin-bottom:.4rem;">Emitido em</div>
      <div style="font-weight:600;color:var(--gray-900);margin-bottom:.5rem;">{{ r.data_geracao }}</div>
      <div class="report-id">REF: RGT-{{ '%08d' % (r.produtores.total or 0) }}</div>
    </div>
  </div>

  <!-- CAIXA COPAR EM DESTAQUE -->
  <div class="caixa-copar">
    <div>
      <div class="titulo">Caixa COPAR — Saldo Acumulado</div>
      <div class="saldo">R$ {{ '%.2f'|format(r.caixa_copar.saldo_atual)|replace('.', ',') }}</div>
      <div class="info">
        Comissão por kg: R$ {{ '%.2f'|format(r.config.get('comissao_por_kg', 0.30)|float)|replace('.', ',') }}
        &nbsp;•&nbsp;
        {{ '%.2f'|format(r.caixa_copar.peso_comissionado)|replace('.', ',') }} kg comissionados
      </div>
    </div>
    <div class="stats">
      <div class="stat">
        <div class="lbl">Comissões</div>
        <div class="val">R$ {{ '%.2f'|format(r.caixa_copar.total_comissao)|replace('.', ',') }}</div>
      </div>
      <div class="stat">
        <div class="lbl">Ajustes</div>
        <div class="val">R$ {{ '%.2f'|format(r.caixa_copar.total_ajustes)|replace('.', ',') }}</div>
      </div>
      <div class="stat">
        <div class="lbl">Retiradas</div>
        <div class="val">R$ {{ '%.2f'|format(r.caixa_copar.total_retiradas)|replace('.', ',') }}</div>
      </div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Produtores</div>
      <div class="value">{{ r.produtores.total }}</div>
      <div class="sub">Cadastrados</div>
    </div>
    <div class="kpi green">
      <div class="label">Estoque Total</div>
      <div class="value">{{ '%.0f'|format(r.estoque.total_kg) }} kg</div>
      <div class="sub">{{ '%.2f'|format(r.estoque.total_industria) }} kg indústria</div>
    </div>
    <div class="kpi blue">
      <div class="label">Vendas Totais</div>
      <div class="value">R$ {{ '%.0f'|format(r.vendas.bruto_total) }}</div>
      <div class="sub">{{ r.vendas.qtd }} venda(s)</div>
    </div>
    <div class="kpi amber">
      <div class="label">Comissão COPAR</div>
      <div class="value">R$ {{ '%.2f'|format(r.caixa_copar.total_comissao)|replace('.', ',') }}</div>
      <div class="sub">Total arrecadado</div>
    </div>
    <div class="kpi ind">
      <div class="label">Horas de Banca</div>
      <div class="value">{{ '%.1f'|format(r.horas_banca.total) }} h</div>
      <div class="sub">{{ r.horas_banca.registros_mes }} no mês atual</div>
    </div>
    <div class="kpi red">
      <div class="label">Pagamentos</div>
      <div class="value">R$ {{ '%.0f'|format(r.pagamentos.total) }}</div>
      <div class="sub">{{ r.pagamentos.qtd }} recibo(s)</div>
    </div>
  </div>

  <!-- CAIXA COPAR POR MÊS -->
  <div class="section">
    <div class="section-title">
      <span>Caixa COPAR — Movimento Mensal (12 meses)</span>
    </div>
    {% if r.caixa_copar.por_mes %}
    <table>
      <thead>
        <tr>
          <th>Mês</th>
          <th class="num">Vendas</th>
          <th class="num">Peso (kg)</th>
          <th class="num">Comissões</th>
          <th class="num">Ajustes</th>
          <th class="num">Retiradas</th>
          <th class="num">Saldo do Mês</th>
        </tr>
      </thead>
      <tbody>
        {% for m in r.caixa_copar.por_mes %}
        <tr>
          <td><strong>{{ m.mes }}</strong></td>
          <td class="num">{{ m.qtd_vendas }}</td>
          <td class="num">{{ '%.2f'|format(m.peso)|replace('.', ',') }}</td>
          <td class="num" style="color:var(--green)">+ R$ {{ '%.2f'|format(m.comissao)|replace('.', ',') }}</td>
          <td class="num" style="color:var(--blue)">{{ 'R$ %.2f'|format(m.ajustes)|replace('.', ',') if m.ajustes > 0 else '—' }}</td>
          <td class="num" style="color:var(--red)">{{ '- R$ %.2f'|format(m.retiradas)|replace('.', ',') if m.retiradas > 0 else '—' }}</td>
          <td class="num"><strong>R$ {{ '%.2f'|format(m.saldo_mes)|replace('.', ',') }}</strong></td>
        </tr>
        {% endfor %}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="3">TOTAL DO PERÍODO</td>
          <td class="num">+ R$ {{ '%.2f'|format(r.caixa_copar.por_mes|sum(attribute='comissao'))|replace('.', ',') }}</td>
          <td class="num">R$ {{ '%.2f'|format(r.caixa_copar.por_mes|sum(attribute='ajustes'))|replace('.', ',') }}</td>
          <td class="num">R$ {{ '%.2f'|format(r.caixa_copar.por_mes|sum(attribute='retiradas'))|replace('.', ',') }}</td>
          <td class="num">R$ {{ '%.2f'|format(r.caixa_copar.por_mes|sum(attribute='saldo_mes'))|replace('.', ',') }}</td>
        </tr>
      </tfoot>
    </table>
    {% else %}
    <div class="empty">Nenhum movimento registrado nos últimos 12 meses.</div>
    {% endif %}
  </div>

  <!-- CAIXA COPAR — ÚLTIMOS MOVIMENTOS -->
  <div class="section">
    <div class="section-title">
      <span>Caixa COPAR — Últimos 30 Movimentos</span>
    </div>
    {% if r.caixa_copar.movimentos %}
    <table>
      <thead>
        <tr>
          <th>Nº</th>
          <th>Data</th>
          <th>Tipo</th>
          <th>Produtor</th>
          <th>Venda Ref.</th>
          <th class="num">Peso (kg)</th>
          <th class="num">Valor</th>
          <th>Descrição</th>
        </tr>
      </thead>
      <tbody>
        {% for m in r.caixa_copar.movimentos %}
        <tr>
          <td class="num">{{ '%05d' % m.id }}</td>
          <td>{{ m.data }}</td>
          <td>
            {% if m.tipo == 'comissao' %}<span class="badge badge-comissao">Comissão</span>
            {% elif m.tipo == 'ajuste' %}<span class="badge badge-ajuste">Ajuste</span>
            {% else %}<span class="badge badge-retirada">Retirada</span>{% endif %}
          </td>
          <td>{{ m.produtor }}</td>
          <td class="num">{{ '#%05d' % m.venda_id if m.venda_id else '—' }}</td>
          <td class="num">{{ '%.3f'|format(m.peso)|replace('.', ',') if m.peso > 0 else '—' }}</td>
          <td class="num" style="font-weight:600;color:{% if m.tipo == 'comissao' %}var(--green){% elif m.tipo == 'retirada' %}var(--red){% else %}var(--blue){% endif %}">
            {% if m.tipo == 'comissao' %}+{% elif m.tipo == 'retirada' %}-{% endif %}R$ {{ '%.2f'|format(m.valor)|replace('.', ',') }}
          </td>
          <td>{{ m.descricao }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Nenhum movimento registrado.</div>
    {% endif %}
  </div>

  <!-- ESTOQUE + INDÚSTRIA -->
  <div class="grid-2">
    <div class="section">
      <div class="section-title">
        <span>Estoque por Local</span>
        <span class="section-total">{{ '%.0f'|format(r.estoque.total_kg) }} kg</span>
      </div>
      {% if r.estoque.por_local %}
      <table>
        <thead><tr><th>Local</th><th class="num">Peso (kg)</th></tr></thead>
        <tbody>
          {% for local, peso in r.estoque.por_local.items() %}
          <tr>
            <td>{{ local }}</td>
            <td class="num">{{ '%.3f'|format(peso)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty">Sem estoque</div>
      {% endif %}
    </div>

    <div class="section">
      <div class="section-title">
        <span>Estoque de Indústria</span>
        <span class="section-total">{{ '%.2f'|format(r.estoque.total_industria)|replace('.', ',') }} kg</span>
      </div>
      {% if r.estoque.industria %}
      <table>
        <thead><tr><th>Classe</th><th class="num">Peso (kg)</th></tr></thead>
        <tbody>
          {% for classe, peso in r.estoque.industria.items() %}
          <tr>
            <td><span class="badge badge-ind">{{ classe }}</span></td>
            <td class="num">{{ '%.3f'|format(peso)|replace('.', ',') }}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr><td>TOTAL</td><td class="num">{{ '%.2f'|format(r.estoque.total_industria)|replace('.', ',') }} kg</td></tr>
        </tfoot>
      </table>
      {% else %}
      <div class="empty">Sem estoque de indústria</div>
      {% endif %}
    </div>
  </div>

  <!-- ESTOQUE POR TIPO -->
  <div class="section">
    <div class="section-title"><span>Estoque por Variedade</span></div>
    {% if r.estoque.por_tipo %}
    <table>
      <thead><tr><th>Variedade</th><th class="num">Peso (kg)</th></tr></thead>
      <tbody>
        {% for tipo, peso in r.estoque.por_tipo.items() %}
        <tr>
          <td>{{ tipo }}</td>
          <td class="num">{{ '%.3f'|format(peso)|replace('.', ',') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Sem estoque</div>
    {% endif %}
  </div>

  <!-- VENDAS POR MÊS -->
  <div class="section">
    <div class="section-title">
      <span>Vendas por Mês (12 meses)</span>
      <span class="section-total">Total: R$ {{ '%.2f'|format(r.vendas.bruto_total)|replace('.', ',') }}</span>
    </div>
    {% if r.vendas.por_mes %}
    <table>
      <thead>
        <tr>
          <th>Mês</th>
          <th class="num">Qtd</th>
          <th class="num">Peso (kg)</th>
          <th class="num">Bruto</th>
          <th class="num">Comissão</th>
          <th class="num">Líquido</th>
        </tr>
      </thead>
      <tbody>
        {% for v in r.vendas.por_mes %}
        <tr>
          <td><strong>{{ v.mes }}</strong></td>
          <td class="num">{{ v.qtd }}</td>
          <td class="num">{{ '%.2f'|format(v.peso)|replace('.', ',') }}</td>
          <td class="num">R$ {{ '%.2f'|format(v.bruto)|replace('.', ',') }}</td>
          <td class="num" style="color:var(--amber)">-R$ {{ '%.2f'|format(v.comissao)|replace('.', ',') }}</td>
          <td class="num"><strong>R$ {{ '%.2f'|format(v.liquido)|replace('.', ',') }}</strong></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Nenhuma venda nos últimos 12 meses.</div>
    {% endif %}
  </div>

  <!-- TOP PRODUTORES -->
  <div class="section">
    <div class="section-title"><span>Top 10 Produtores por Volume</span></div>
    {% if r.top_produtores %}
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Produtor</th>
          <th>Matrícula</th>
          <th class="num">Peso (kg)</th>
          <th class="num">Valor Bruto</th>
          <th class="num">Comissão COPAR</th>
        </tr>
      </thead>
      <tbody>
        {% for p in r.top_produtores %}
        <tr>
          <td class="num">{{ loop.index }}</td>
          <td><strong>{{ p.nome }}</strong></td>
          <td class="num">{{ p.matricula }}</td>
          <td class="num">{{ '%.2f'|format(p.peso)|replace('.', ',') }}</td>
          <td class="num">R$ {{ '%.2f'|format(p.valor)|replace('.', ',') }}</td>
          <td class="num" style="color:var(--amber)">R$ {{ '%.2f'|format(p.comissao)|replace('.', ',') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Nenhuma venda registrada.</div>
    {% endif %}
  </div>

  <!-- HORAS DE BANCA -->
  <div class="section">
    <div class="section-title">
      <span>Horas de Banca por Produtor</span>
      <span class="section-total">{{ '%.2f'|format(r.horas_banca.total) }} h totais</span>
    </div>
    {% if r.horas_banca.por_produtor %}
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Produtor</th>
          <th>Matrícula</th>
          <th class="num">Horas</th>
          <th class="num">Valor (R$)</th>
        </tr>
      </thead>
      <tbody>
        {% set vh = r.config.get('valor_hora_banca', '16.00')|float %}
        {% for h in r.horas_banca.por_produtor %}
        <tr>
          <td class="num">{{ loop.index }}</td>
          <td><strong>{{ h.nome }}</strong></td>
          <td class="num">{{ h.matricula }}</td>
          <td class="num">{{ '%.2f'|format(h.horas) }} h</td>
          <td class="num">R$ {{ '%.2f'|format(h.horas * vh)|replace('.', ',') }}</td>
        </tr>
        {% endfor %}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="3">TOTAL GERAL</td>
          <td class="num">{{ '%.2f'|format(r.horas_banca.total) }} h</td>
          <td class="num">R$ {{ '%.2f'|format(r.horas_banca.total * vh)|replace('.', ',') }}</td>
        </tr>
      </tfoot>
    </table>
    {% else %}
    <div class="empty">Nenhum registro de horas de banca.</div>
    {% endif %}
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <div>
      <strong>{{ r.config.nome_empresa or 'COPAR' }}</strong> &mdash;
      Documento gerado automaticamente pelo sistema COPAR Web
    </div>
    <div>{{ r.data_geracao }} &mdash; REF RGT-{{ '%08d' % (r.produtores.total or 0) }}</div>
  </div>

</div>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════════════════

def registrar_rotas_relatorio_geral(app):

    @app.route('/gerente/relatorio-geral')
    def gerente_relatorio_geral_html():
        if not verificar_acesso_gerente():
            return redirect(url_for('login'))
        r = obter_relatorio_geral_completo()
        if not r:
            return "Erro ao gerar relatório", 500
        return render_template_string(HTML_RELATORIO_GERAL, r=r)

    @app.route('/api/gerente/relatorio-geral')
    def api_gerente_relatorio_geral():
        if not verificar_acesso_gerente():
            return jsonify({'erro': 'Não autorizado'}), 403
        return jsonify(obter_relatorio_geral_completo() or {})

    print("✅ Módulo de Relatório Geral ativado!")
