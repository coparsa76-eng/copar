# -*- coding: utf-8 -*-
"""
MÓDULO DE PAGAMENTOS v2
- Mostra os descontos JÁ APLICADOS na venda (comissão COPAR + extras)
- Desconta hora de banca proporcional ao peso vendido
- NÃO recalcula descontos (já foram aplicados na venda)
"""
from flask import render_template_string, jsonify, request, session
import psycopg
import logging

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


def _obter_valor_hora_banca():
    try:
        from modulo_configuracoes import obter_valor_hora_banca
        return obter_valor_hora_banca()
    except Exception:
        return 16.00


def _obter_configuracoes():
    try:
        from modulo_configuracoes import obter_configuracoes
        return obter_configuracoes()
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════
# HORA DE BANCA PROPORCIONAL
# ══════════════════════════════════════════════════════════════════════════

def calcular_desconto_hora_banca(produtor_id, vendas_ids):
    """
    Calcula o desconto de hora de banca proporcional:
    
    - Lê TODAS as horas registradas para o produtor (registros_horas_banca)
    - Lê o peso total atual em estoque
    - Para cada venda selecionada, calcula a proporção:
        horas_venda = horas_totais × (peso_venda / peso_estoque_atual)
    - Multiplica pelo valor da hora
    
    IMPORTANTE: as horas NÃO são debitadas — apenas calculadas como desconto.
    """
    conn = conectar_banco()
    if not conn:
        return {'total': 0, 'por_venda': {}, 'valor_hora': 0, 'horas_totais': 0}

    try:
        cur = conn.cursor()
        valor_hora = _obter_valor_hora_banca()

        # 1. Total de horas registradas para o produtor
        cur.execute("""
            SELECT COALESCE(SUM(horas), 0) FROM registros_horas_banca
            WHERE produtor_id = %s
        """, (produtor_id,))
        horas_totais = float(cur.fetchone()[0])

        # 2. Peso total do estoque atual
        cur.execute("""
            SELECT COALESCE(SUM(peso), 0) FROM estoque
            WHERE produtor_id = %s AND peso > 0
        """, (produtor_id,))
        peso_estoque = float(cur.fetchone()[0])

        # 3. Distribuição proporcional por venda
        por_venda = {}
        total_desconto = 0

        if peso_estoque > 0 and horas_totais > 0:
            for venda_id in vendas_ids:
                cur.execute("""
                    SELECT peso FROM vendas WHERE id = %s AND produtor_id = %s
                """, (venda_id, produtor_id))
                row = cur.fetchone()
                if not row:
                    continue
                peso_venda = float(row[0])

                proporcao = peso_venda / peso_estoque
                horas_venda = horas_totais * proporcao
                valor_hb = round(horas_venda * valor_hora, 2)

                por_venda[venda_id] = {
                    'horas': round(horas_venda, 3),
                    'valor': valor_hb,
                    'peso_venda': peso_venda,
                }
                total_desconto += valor_hb

        cur.close()
        conn.close()
        return {
            'total': round(total_desconto, 2),
            'por_venda': por_venda,
            'valor_hora': valor_hora,
            'horas_totais': horas_totais,
            'peso_estoque': peso_estoque,
        }
    except Exception as e:
        logger.error(f"Erro calcular_desconto_hora_banca: {e}")
        return {'total': 0, 'por_venda': {}, 'valor_hora': 0, 'horas_totais': 0}


# ══════════════════════════════════════════════════════════════════════════
# BUSCAS
# ══════════════════════════════════════════════════════════════════════════

def buscar_produtor_por_matricula(matricula):
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, matricula, COALESCE(cpf, '')
            FROM produtores WHERE matricula = %s
        """, (matricula.strip(),))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            return {'id': r[0], 'nome': r[1], 'matricula': r[2], 'cpf': r[3]}
        return None
    except Exception as e:
        logger.error(f"Erro buscar_produtor: {e}")
        return None


def buscar_vendas_pendentes(produtor_id):
    """Retorna vendas não pagas com todos os valores de desconto já aplicados"""
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_kg,
                   v.valor_total, v.valor_produtor,
                   COALESCE(v.desconto_comissao, 0) AS desconto_comissao,
                   COALESCE(v.desconto_extra, 0) AS desconto_extra,
                   COALESCE(v.valor_liquido_produtor, v.valor_produtor) AS valor_liquido,
                   v.status_pagamento,
                   COALESCE(cp.saldo, v.valor_produtor) AS saldo,
                   COALESCE(cp.valor_pago, 0) AS pago,
                   v.origem_estoque
            FROM vendas v
            LEFT JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s AND v.status_pagamento != 'Pago'
            ORDER BY v.data_venda ASC
        """, (produtor_id,))

        vendas = []
        for r in cur.fetchall():
            vendas.append({
                'id': r[0],
                'data': r[1].strftime("%d/%m/%Y") if r[1] else "",
                'tipo': r[2] or "",
                'classe': r[3] or "",
                'peso': float(r[4] or 0),
                'valor_kg': float(r[5] or 0),
                'valor_total': float(r[6] or 0),
                'valor_produtor': float(r[7] or 0),
                'desconto_comissao': float(r[8]),
                'desconto_extra': float(r[9]),
                'valor_liquido': float(r[10]),
                'status': r[11],
                'saldo': float(r[12] or 0),
                'pago': float(r[13] or 0),
                'origem': r[14] or "",
            })
        cur.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro buscar_vendas_pendentes: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════
# SIMULAÇÃO DE PAGAMENTO
# ══════════════════════════════════════════════════════════════════════════

def simular_pagamento(produtor_id, vendas_ids):
    """
    Calcula o valor líquido final considerando:
    - Valor total das vendas (já com descontos aplicados)
    - Desconto de hora de banca proporcional
    """
    conn = conectar_banco()
    if not conn:
        return None

    try:
        cur = conn.cursor()

        if not vendas_ids:
            cur.close()
            conn.close()
            return None

        placeholders = ','.join(['%s'] * len(vendas_ids))
        cur.execute(f"""
            SELECT v.id, v.peso, v.valor_total, v.valor_produtor,
                   COALESCE(v.desconto_comissao, 0) AS desconto_comissao,
                   COALESCE(v.desconto_extra, 0) AS desconto_extra,
                   COALESCE(v.valor_liquido_produtor, v.valor_produtor) AS valor_liquido,
                   v.tipo_alho, v.classe, v.valor_kg,
                   v.origem_estoque
            FROM vendas v
            WHERE v.id IN ({placeholders}) AND v.produtor_id = %s
        """, (*vendas_ids, produtor_id))
        vendas = cur.fetchall()

        if not vendas:
            cur.close()
            conn.close()
            return None

        # Totais
        valor_bruto = 0
        total_comissao = 0
        total_extra = 0
        total_liquido_vendas = 0
        for v in vendas:
            valor_bruto += float(v[2])
            total_comissao += float(v[4])
            total_extra += float(v[5])
            total_liquido_vendas += float(v[6])

        # Desconto hora banca
        hb = calcular_desconto_hora_banca(produtor_id, list(vendas_ids))

        valor_final = round(total_liquido_vendas - hb['total'], 2)
        if valor_final < 0:
            valor_final = 0

        # Horas totais do produtor
        cur.execute("""
            SELECT COALESCE(SUM(horas), 0) FROM registros_horas_banca
            WHERE produtor_id = %s
        """, (produtor_id,))
        horas_registradas = float(cur.fetchone()[0])

        cur.close()
        conn.close()

        return {
            'valor_bruto': round(valor_bruto, 2),
            'comissao_copar': round(total_comissao, 2),
            'descontos_extras': round(total_extra, 2),
            'valor_liquido_vendas': round(total_liquido_vendas, 2),
            'desconto_hora_banca': {
                'total': hb['total'],
                'valor_hora': hb['valor_hora'],
                'horas_registradas': horas_registradas,
                'horas_descontadas': round(hb['total'] / hb['valor_hora'], 3) if hb['valor_hora'] > 0 else 0,
                'por_venda': hb['por_venda'],
            },
            'total_descontos_hb': hb['total'],
            'valor_liquido': valor_final,
            'vendas': [{
                'id': v[0],
                'peso': float(v[1]),
                'valor_total': float(v[2]),
                'valor_produtor': float(v[3]),
                'comissao': float(v[4]),
                'extra': float(v[5]),
                'liquido': float(v[6]),
                'tipo': v[7],
                'classe': v[8],
                'valor_kg': float(v[9] or 0),
                'origem': v[10] or "",
            } for v in vendas]
        }
    except Exception as e:
        logger.error(f"Erro simular_pagamento: {e}")
        import traceback
        traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════════════
# REGISTRAR PAGAMENTO
# ══════════════════════════════════════════════════════════════════════════

def registrar_pagamento(produtor_id, vendas_ids, valor_pago, forma_pagamento, observacao):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()

        cur.execute("SELECT nome FROM produtores WHERE id = %s", (produtor_id,))
        row = cur.fetchone()
        nome_prod = row[0] if row else 'Produtor'

        obs_final = observacao or ''
        cur.execute("""
            INSERT INTO pagamentos (produtor_id, valor_total, forma_pagamento, observacoes)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (produtor_id, valor_pago, forma_pagamento, obs_final))
        pagamento_id = cur.fetchone()[0]

        restante = valor_pago
        for venda_id in vendas_ids:
            if restante <= 0.01:
                break

            cur.execute("SELECT id, saldo FROM creditos_produtor WHERE venda_id = %s", (venda_id,))
            credito = cur.fetchone()

            if not credito:
                cur.execute("SELECT valor_produtor FROM vendas WHERE id = %s", (venda_id,))
                vp = cur.fetchone()
                if not vp:
                    continue
                cur.execute("""
                    INSERT INTO creditos_produtor (produtor_id, venda_id, valor_credito, saldo, valor_pago)
                    VALUES (%s, %s, %s, %s, 0) RETURNING id, saldo
                """, (produtor_id, venda_id, float(vp[0]), float(vp[0])))
                credito = cur.fetchone()

            credito_id, saldo_atual = credito[0], float(credito[1])
            if saldo_atual <= 0:
                continue

            valor_pagar = min(restante, saldo_atual)

            cur.execute("""
                INSERT INTO itens_pagos (pagamento_id, credito_id, valor_pago)
                VALUES (%s, %s, %s)
            """, (pagamento_id, credito_id, valor_pagar))

            cur.execute("""
                UPDATE creditos_produtor
                SET valor_pago = valor_pago + %s, saldo = saldo - %s
                WHERE id = %s
            """, (valor_pagar, valor_pagar, credito_id))

            novo_saldo = saldo_atual - valor_pagar
            if novo_saldo <= 0.01:
                cur.execute("UPDATE vendas SET status_pagamento = 'Pago' WHERE id = %s", (venda_id,))
            else:
                cur.execute("UPDATE vendas SET status_pagamento = 'Parcial' WHERE id = %s", (venda_id,))

            restante -= valor_pagar

        conn.commit()
        cur.close()
        conn.close()

        return {
            'sucesso': True,
            'mensagem': f'Pagamento #{pagamento_id} registrado para {nome_prod}\nValor: R$ {valor_pago:.2f}',
            'pagamento_id': pagamento_id
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro registrar_pagamento: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


def registrar_adiantamento(produtor_id, valor, forma_pagamento, observacao):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        obs = f"Adiantamento - {observacao}" if observacao else "Adiantamento"
        cur.execute("""
            INSERT INTO pagamentos (produtor_id, valor_total, forma_pagamento, observacoes)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (produtor_id, valor, forma_pagamento, obs))
        pid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {'sucesso': True, 'mensagem': f'Adiantamento #{pid} registrado!', 'pagamento_id': pid}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {'sucesso': False, 'mensagem': str(e)}


def gerar_recibo(produtor_id, pagamento_id):
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT nome, matricula, COALESCE(cpf,'') FROM produtores WHERE id = %s", (produtor_id,))
        prod = cur.fetchone()

        cur.execute("""
            SELECT data_pagamento, valor_total, forma_pagamento, observacoes
            FROM pagamentos WHERE id = %s
        """, (pagamento_id,))
        pag = cur.fetchone()

        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_produtor, ip.valor_pago,
                   COALESCE(v.desconto_comissao, 0) AS comissao,
                   COALESCE(v.desconto_extra, 0) AS extra
            FROM itens_pagos ip
            JOIN creditos_produtor cp ON ip.credito_id = cp.id
            JOIN vendas v ON cp.venda_id = v.id
            WHERE ip.pagamento_id = %s
        """, (pagamento_id,))
        vendas = cur.fetchall()

        cur.close()
        conn.close()

        return {
            'produtor': {'nome': prod[0], 'matricula': prod[1], 'cpf': prod[2]},
            'pagamento': {
                'id': pagamento_id,
                'data': pag[0].strftime("%d/%m/%Y %H:%M") if pag[0] else "",
                'valor': float(pag[1]),
                'forma': pag[2],
                'obs': pag[3] or ""
            },
            'vendas': [{
                'id': v[0],
                'data': v[1].strftime("%d/%m/%Y") if v[1] else "",
                'tipo': v[2], 'classe': v[3],
                'peso': float(v[4]),
                'total': float(v[5]),
                'pago': float(v[6]),
                'comissao': float(v[7]),
                'extra': float(v[8]),
            } for v in vendas],
            'config': _obter_configuracoes(),
        }
    except Exception as e:
        logger.error(f"Erro gerar_recibo: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════
# HTML PAGAMENTOS
# ══════════════════════════════════════════════════════════════════════════

HTML_PAGAMENTOS = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pagamentos – COPAR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#0a3d2c;--primary-light:#1a6b4d;
  --gray-50:#f9fafb;--gray-100:#f3f4f6;--gray-200:#e5e7eb;--gray-300:#d1d5db;
  --gray-500:#6b7280;--gray-700:#374151;--gray-900:#111827;
  --red:#991b1b;--red-light:#fee2e2;--green:#166534;--green-light:#dcfce7;
  --amber:#92400e;--amber-light:#fef3c7;--blue:#1e40af;--blue-light:#dbeafe;
  --ind:#8e44ad;--ind-light:#f4ecf7;
  --mono:'JetBrains Mono',monospace;
}
body{font-family:'Inter',sans-serif;background:var(--gray-100);color:var(--gray-900);min-height:100dvh;font-size:14px}
nav{background:var(--primary);padding:.9rem 1.5rem;display:flex;align-items:center;
    justify-content:space-between;position:sticky;top:0;z-index:100;gap:1rem}
.nav-brand{color:#fff;font-weight:700;font-size:1rem}
.nav-back{color:rgba(255,255,255,.85);text-decoration:none;font-size:.8rem;
          border:1px solid rgba(255,255,255,.3);padding:.4rem .9rem;border-radius:6px}
.nav-back:hover{background:rgba(255,255,255,.15)}
.wrap{max-width:1100px;margin:0 auto;padding:1.5rem}
.card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:1rem;overflow:hidden}
.card-header{background:#fff;border-bottom:1px solid var(--gray-200);padding:.9rem 1.25rem;
             font-weight:600;font-size:.85rem;color:var(--primary);text-transform:uppercase;letter-spacing:.06em}
.card-body{padding:1.25rem}

.busca{display:grid;grid-template-columns:1fr auto;gap:.75rem}
.busca input{padding:.7rem .9rem;border:1.5px solid var(--gray-300);border-radius:6px;
             font-family:inherit;font-size:.9rem;width:100%}
.busca button{padding:.7rem 1.5rem;background:var(--primary);color:#fff;border:none;
              border-radius:6px;font-weight:600;cursor:pointer;font-family:inherit;font-size:.88rem}
.busca button:hover{background:var(--primary-light)}

.produtor-info{background:var(--gray-50);border-left:3px solid var(--primary);
               padding:1rem 1.15rem;border-radius:4px;margin-top:1rem;display:none}
.produtor-info.show{display:block}
.produtor-info .nome{font-size:1.05rem;font-weight:700;color:var(--primary);margin-bottom:.3rem}
.produtor-info .meta{font-size:.8rem;color:var(--gray-500);font-family:var(--mono)}

.vendas-lista{max-height:500px;overflow-y:auto;border:1px solid var(--gray-200);border-radius:6px}
.venda-item{display:grid;grid-template-columns:auto 90px 140px 100px 90px 90px 90px 90px;
            gap:.6rem;align-items:center;padding:.75rem 1rem;
            border-bottom:1px solid var(--gray-100);cursor:pointer;transition:background .15s;font-size:.82rem}
.venda-item:last-child{border-bottom:none}
.venda-item:hover{background:var(--gray-50)}
.venda-item.sel{background:var(--green-light);border-left:3px solid var(--green)}
.venda-item input[type=checkbox]{width:16px;height:16px;cursor:pointer}
.venda-data{font-size:.75rem;color:var(--gray-500)}
.venda-produto{font-weight:600}
.venda-produto small{display:block;font-size:.7rem;color:var(--gray-500);font-weight:400}
.venda-num,.venda-valor{font-family:var(--mono);font-weight:600;text-align:right}
.venda-valor.comissao{color:var(--amber)}
.venda-valor.liquido{color:var(--primary)}
.venda-status{font-size:.65rem;padding:.15rem .45rem;border-radius:3px;
              font-weight:700;text-transform:uppercase;letter-spacing:.04em;display:inline-block}
.s-pendente{background:var(--amber-light);color:var(--amber)}
.s-parcial{background:var(--blue-light);color:var(--blue)}

.venda-header{display:grid;grid-template-columns:auto 90px 140px 100px 90px 90px 90px 90px;
              gap:.6rem;padding:.6rem 1rem;background:var(--gray-100);font-size:.68rem;
              font-weight:700;text-transform:uppercase;color:var(--gray-500);letter-spacing:.04em}

/* SIMULAÇÃO */
.simulacao{background:var(--gray-50);border:1px solid var(--gray-200);border-radius:6px;
           padding:1rem 1.15rem;margin-top:1rem}
.simulacao h4{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;
              color:var(--gray-500);font-weight:700;margin-bottom:.75rem}
.sim-linha{display:flex;justify-content:space-between;padding:.4rem 0;
           font-size:.85rem;border-bottom:1px solid var(--gray-200)}
.sim-linha:last-child{border-bottom:none}
.sim-linha.sub{padding-left:1.5rem;font-size:.78rem;color:var(--gray-500)}
.sim-linha.total{border-top:2px solid var(--primary);border-bottom:none;
                 margin-top:.5rem;padding-top:.75rem;font-weight:700;font-size:1rem}
.sim-linha .val{font-family:var(--mono);font-weight:600}
.sim-linha .val.neg{color:var(--red)}
.sim-linha .val.pos{color:var(--green)}
.sim-linha.total .val{color:var(--primary);font-size:1.2rem}

/* FORM */
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem}
.form-group label{font-size:.7rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.06em;color:var(--gray-500);display:block;margin-bottom:.3rem}
.form-group input,.form-group select{
  width:100%;padding:.65rem .85rem;border:1.5px solid var(--gray-300);
  border-radius:6px;font-family:inherit;font-size:.88rem}
.form-group input:focus,.form-group select:focus{outline:none;border-color:var(--primary)}

.btn-acao{padding:.9rem;border-radius:6px;font-family:inherit;font-weight:700;
          font-size:.95rem;cursor:pointer;width:100%;margin-top:1rem;border:none}
.btn-pagar{background:var(--primary);color:#fff}
.btn-pagar:hover{background:var(--primary-light)}
.btn-pagar:disabled{opacity:.5;cursor:not-allowed}
.btn-adiantar{background:var(--amber);color:#fff}
.btn-adiantar:hover{background:#78350f}

.toast{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%) translateY(120px);
       background:var(--gray-900);color:#fff;padding:.75rem 1.5rem;border-radius:999px;
       font-size:.88rem;font-weight:600;z-index:999;transition:transform .3s;
       max-width:90%;text-align:center}
.toast.show{transform:translateX(-50%) translateY(0)}
.toast.ok{background:var(--green)}
.toast.err{background:var(--red)}

.spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);
      border-top-color:#fff;border-radius:50%;animation:sp .6s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}

/* MODAL */
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;
       align-items:center;justify-content:center;padding:1rem}
.modal.open{display:flex}
.modal-content{background:#fff;border-radius:8px;max-width:640px;width:100%;
               max-height:90vh;overflow:auto}
.modal-header{padding:1rem 1.25rem;border-bottom:1px solid var(--gray-200);
              font-weight:700;display:flex;justify-content:space-between;align-items:center}
.modal-body{padding:1.25rem;font-size:.85rem}
.modal-footer{padding:1rem 1.25rem;border-top:1px solid var(--gray-200);
              display:flex;justify-content:flex-end;gap:.5rem}
.btn-modal{padding:.5rem 1rem;border-radius:6px;font-family:inherit;
           font-size:.82rem;font-weight:600;cursor:pointer;border:1px solid var(--gray-300);
           background:#fff;color:var(--gray-700)}
.btn-modal.primary{background:var(--primary);color:#fff;border-color:var(--primary)}
.recibo-empresa{text-align:center;padding-bottom:1rem;border-bottom:2px solid var(--primary);margin-bottom:1rem}
.recibo-empresa .nome{font-size:1.1rem;font-weight:800;color:var(--primary);margin-bottom:.2rem}
.recibo-empresa .info{font-size:.75rem;color:var(--gray-500)}
.recibo-linha{display:flex;justify-content:space-between;padding:.35rem 0;font-size:.82rem;
              border-bottom:1px dashed var(--gray-200)}
.recibo-linha.total{border-top:2px solid var(--primary);border-bottom:none;
                    margin-top:.5rem;padding-top:.75rem;font-weight:700;font-size:1rem}
.recibo-linha .desc{color:var(--amber);font-size:.78rem}
.recibo-linha .desc-extra{color:var(--gray-500);font-size:.72rem;padding-left:1rem}

@media(max-width:800px){
  .venda-item,.venda-header{grid-template-columns:auto 1fr 1fr;gap:.4rem;font-size:.75rem}
  .venda-col-oculta{display:none}
  .form-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<nav>
  <div class="nav-brand">COPAR — Pagamentos</div>
  <a href="/gerente" class="nav-back">Voltar</a>
</nav>

<div class="wrap">
  <div class="card">
    <div class="card-header">Buscar Produtor</div>
    <div class="card-body">
      <div class="busca">
        <input type="text" id="matricula" placeholder="Digite a matrícula do produtor" autocomplete="off">
        <button id="btnBuscar">Buscar</button>
      </div>
      <div id="produtorInfo" class="produtor-info"></div>
    </div>
  </div>

  <div class="card" id="cardVendas" style="display:none">
    <div class="card-header">Vendas Pendentes</div>
    <div class="card-body">
      <div class="vendas-lista">
        <div class="venda-header">
          <span></span>
          <span>Data</span>
          <span>Produto</span>
          <span style="text-align:right">Peso</span>
          <span style="text-align:right">Bruto</span>
          <span style="text-align:right">COPAR</span>
          <span style="text-align:right">Extra</span>
          <span style="text-align:right">Líquido</span>
        </div>
        <div id="vendasLista"></div>
      </div>

      <div class="simulacao" id="simulacao" style="display:none">
        <h4>Simulação do Pagamento</h4>
        <div id="simLinhas"></div>
      </div>

      <div class="form-grid">
        <div class="form-group">
          <label>Valor a Pagar (R$)</label>
          <input type="number" id="valorPagar" step="0.01" placeholder="0,00">
        </div>
        <div class="form-group">
          <label>Forma de Pagamento</label>
          <select id="formaPagamento">
            <option value="">Selecione</option>
            {% for f in formas %}<option value="{{ f }}">{{ f }}</option>{% endfor %}
          </select>
        </div>
      </div>
      <div class="form-group" style="margin-top:1rem">
        <label>Observação (opcional)</label>
        <input type="text" id="observacao" placeholder="Ex: Pagamento referente ao lote de maio">
      </div>

      <button class="btn-acao btn-pagar" id="btnPagar">Realizar Pagamento</button>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Adiantamento (sem venda vinculada)</div>
    <div class="card-body">
      <div class="form-grid">
        <div class="form-group">
          <label>Valor (R$)</label>
          <input type="number" id="valorAdiantamento" step="0.01" placeholder="0,00">
        </div>
        <div class="form-group">
          <label>Forma</label>
          <select id="formaAdiantamento">
            <option value="">Selecione</option>
            {% for f in formas %}<option value="{{ f }}">{{ f }}</option>{% endfor %}
          </select>
        </div>
      </div>
      <div class="form-group" style="margin-top:1rem">
        <label>Observação</label>
        <input type="text" id="obsAdiantamento" placeholder="Motivo do adiantamento">
      </div>
      <button class="btn-acao btn-adiantar" id="btnAdiantar">Registrar Adiantamento</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<div class="modal" id="modalRecibo">
  <div class="modal-content">
    <div class="modal-header">
      <span>Recibo de Pagamento</span>
      <button class="btn-modal" onclick="fecharModal()">X</button>
    </div>
    <div class="modal-body" id="reciboBody"></div>
    <div class="modal-footer">
      <button class="btn-modal" onclick="fecharModal()">Fechar</button>
      <button class="btn-modal primary" onclick="imprimirRecibo()">Imprimir</button>
    </div>
  </div>
</div>

<script>
let produtorAtual = null;
let vendasPendentes = [];
let vendasSelecionadas = new Set();

const fmt = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtKg = v => Number(v).toLocaleString('pt-BR', {minimumFractionDigits:3, maximumFractionDigits:3}) + ' kg';

function toast(msg, tipo='ok', dur=4000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${tipo}`;
  clearTimeout(t._t);
  if (dur > 0) t._t = setTimeout(() => t.classList.remove('show'), dur);
}

document.getElementById('matricula').addEventListener('keypress', e => {
  if (e.key === 'Enter') document.getElementById('btnBuscar').click();
});

document.getElementById('btnBuscar').onclick = async () => {
  const mat = document.getElementById('matricula').value.trim();
  if (!mat) { toast('Digite uma matrícula', 'err'); return; }
  try {
    const r = await fetch('/api/pagamentos/buscar-produtor', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({matricula: mat})
    });
    const d = await r.json();
    if (!d.encontrado) {
      toast('Produtor não encontrado', 'err');
      document.getElementById('produtorInfo').classList.remove('show');
      document.getElementById('cardVendas').style.display = 'none';
      return;
    }
    produtorAtual = d.produtor;
    document.getElementById('produtorInfo').innerHTML = `
      <div class="nome">${d.produtor.nome}</div>
      <div class="meta">Matrícula: ${d.produtor.matricula} | CPF: ${d.produtor.cpf || '---'}</div>
      <div class="meta" style="margin-top:.4rem;color:var(--green);font-weight:700;font-size:.95rem">
        Saldo pendente: ${fmt(d.saldo_total)}
      </div>
    `;
    document.getElementById('produtorInfo').classList.add('show');
    await carregarVendas(produtorAtual.id);
  } catch(e) { toast('Erro de comunicação', 'err'); }
};

async function carregarVendas(pid) {
  const r = await fetch('/api/pagamentos/vendas-pendentes', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({produtor_id: pid})
  });
  const d = await r.json();
  vendasPendentes = d.vendas || [];
  vendasSelecionadas.clear();
  renderizarVendas();
  document.getElementById('cardVendas').style.display = vendasPendentes.length ? 'block' : 'none';
  if (!vendasPendentes.length) toast('Produtor não possui vendas pendentes', 'ok');
}

function renderizarVendas() {
  const c = document.getElementById('vendasLista');
  if (!vendasPendentes.length) {
    c.innerHTML = '<div style="padding:1.5rem;text-align:center;color:var(--gray-500)">Nenhuma venda pendente</div>';
    return;
  }
  c.innerHTML = vendasPendentes.map(v => {
    const isInd = v.classe.startsWith('Indústria');
    return `
    <div class="venda-item ${vendasSelecionadas.has(v.id) ? 'sel' : ''}" onclick="toggleVenda(${v.id})">
      <input type="checkbox" ${vendasSelecionadas.has(v.id) ? 'checked' : ''} onclick="event.stopPropagation();toggleVenda(${v.id})">
      <div class="venda-data">${v.data}</div>
      <div class="venda-produto">${v.classe}
        <small>${v.tipo} · ${v.origem}</small>
      </div>
      <div class="venda-num venda-col-oculta">${fmtKg(v.peso)}</div>
      <div class="venda-num venda-col-oculta">${fmt(v.valor_total)}</div>
      <div class="venda-num comissao venda-col-oculta">-${fmt(v.desconto_comissao)}</div>
      <div class="venda-num venda-col-oculta" style="color:var(--gray-500)">${v.desconto_extra > 0 ? '-' + fmt(v.desconto_extra) : '—'}</div>
      <div class="venda-num liquido">${fmt(v.valor_liquido)}</div>
    </div>
  `;
  }).join('');
}

function toggleVenda(id) {
  if (vendasSelecionadas.has(id)) vendasSelecionadas.delete(id);
  else vendasSelecionadas.add(id);
  renderizarVendas();
  atualizarSimulacao();
}

async function atualizarSimulacao() {
  const sim = document.getElementById('simulacao');
  if (!vendasSelecionadas.size) {
    sim.style.display = 'none';
    document.getElementById('valorPagar').value = '';
    return;
  }
  sim.style.display = 'block';
  document.getElementById('simLinhas').innerHTML = '<div style="text-align:center;padding:1rem;color:var(--gray-500)">Calculando...</div>';

  try {
    const r = await fetch('/api/pagamentos/simular', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        produtor_id: produtorAtual.id,
        vendas_ids: Array.from(vendasSelecionadas)
      })
    });
    const d = await r.json();

    let html = '';
    html += `<div class="sim-linha"><span>Valor Bruto das Vendas</span><span class="val">${fmt(d.valor_bruto)}</span></div>`;

    if (d.comissao_copar > 0) {
      html += `<div class="sim-linha" style="color:var(--red)">
        <span>(-) Comissão COPAR (já aplicada)</span>
        <span class="val neg">- ${fmt(d.comissao_copar)}</span>
      </div>`;
    }

    if (d.descontos_extras > 0) {
      html += `<div class="sim-linha" style="color:var(--red)">
        <span>(-) Descontos Extras (já aplicados)</span>
        <span class="val neg">- ${fmt(d.descontos_extras)}</span>
      </div>`;
    }

    html += `<div class="sim-linha" style="background:var(--blue-light);padding:.5rem .75rem;border-radius:4px;border:none;margin-top:.5rem">
      <span><strong>Líquido das Vendas</strong></span>
      <span class="val" style="color:var(--blue)">${fmt(d.valor_liquido_vendas)}</span>
    </div>`;

    const hb = d.desconto_hora_banca;
    if (hb.total > 0) {
      html += `<div class="sim-linha" style="color:var(--red);margin-top:.75rem">
        <span>(-) Horas de Banca (${hb.horas_descontadas.toFixed(2)}h × ${fmt(hb.valor_hora)})</span>
        <span class="val neg">- ${fmt(hb.total)}</span>
      </div>`;
      html += `<div class="sim-linha sub"><span>Total de horas registradas: ${hb.horas_registradas.toFixed(2)}h</span><span></span></div>`;
    } else if (hb.horas_registradas > 0) {
      html += `<div class="sim-linha sub" style="margin-top:.75rem"><span>Horas de banca registradas (não descontadas nesta venda): ${hb.horas_registradas.toFixed(2)}h</span><span></span></div>`;
    }

    html += `<div class="sim-linha total"><span>Valor Líquido a Pagar</span><span class="val">${fmt(d.valor_liquido)}</span></div>`;

    document.getElementById('simLinhas').innerHTML = html;
    document.getElementById('valorPagar').value = d.valor_liquido.toFixed(2);
  } catch(e) {
    console.error(e);
    document.getElementById('simLinhas').innerHTML = '<div style="color:var(--red)">Erro ao calcular</div>';
  }
}

document.getElementById('btnPagar').onclick = async () => {
  if (!produtorAtual) { toast('Selecione um produtor', 'err'); return; }
  if (!vendasSelecionadas.size) { toast('Selecione ao menos uma venda', 'err'); return; }

  const valor = parseFloat(document.getElementById('valorPagar').value);
  const forma = document.getElementById('formaPagamento').value;
  const obs = document.getElementById('observacao').value;

  if (!forma) { toast('Selecione a forma de pagamento', 'err'); return; }
  if (!valor || valor <= 0) { toast('Valor inválido', 'err'); return; }

  if (!confirm(`Confirmar pagamento de ${fmt(valor)} para ${produtorAtual.nome}?`)) return;

  const btn = document.getElementById('btnPagar');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Processando...';

  try {
    const r = await fetch('/api/pagamentos/registrar', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        produtor_id: produtorAtual.id,
        vendas_ids: Array.from(vendasSelecionadas),
        valor_pago: valor,
        forma_pagamento: forma,
        observacao: obs
      })
    });
    const d = await r.json();
    if (d.sucesso) {
      toast(d.mensagem, 'ok');
      await gerarRecibo(d.pagamento_id, produtorAtual.id);
      await carregarVendas(produtorAtual.id);
      document.getElementById('observacao').value = '';
    } else {
      toast(d.mensagem, 'err');
    }
  } catch(e) { toast('Erro ao processar', 'err'); }
  finally {
    btn.disabled = false;
    btn.innerHTML = 'Realizar Pagamento';
  }
};

document.getElementById('btnAdiantar').onclick = async () => {
  if (!produtorAtual) { toast('Selecione um produtor', 'err'); return; }
  const valor = parseFloat(document.getElementById('valorAdiantamento').value);
  const forma = document.getElementById('formaAdiantamento').value;
  const obs = document.getElementById('obsAdiantamento').value;
  if (!forma) { toast('Selecione a forma', 'err'); return; }
  if (!valor || valor <= 0) { toast('Valor inválido', 'err'); return; }
  if (!confirm(`Confirmar adiantamento de ${fmt(valor)}?`)) return;

  const btn = document.getElementById('btnAdiantar');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Processando...';
  try {
    const r = await fetch('/api/pagamentos/adiantar', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({produtor_id: produtorAtual.id, valor, forma_pagamento: forma, observacao: obs})
    });
    const d = await r.json();
    if (d.sucesso) {
      toast(d.mensagem, 'ok');
      await gerarRecibo(d.pagamento_id, produtorAtual.id);
      document.getElementById('valorAdiantamento').value = '';
      document.getElementById('obsAdiantamento').value = '';
    } else toast(d.mensagem, 'err');
  } catch(e) { toast('Erro ao registrar', 'err'); }
  finally {
    btn.disabled = false;
    btn.innerHTML = 'Registrar Adiantamento';
  }
};

async function gerarRecibo(pagamentoId, produtorId) {
  try {
    const r = await fetch('/api/pagamentos/recibo', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pagamento_id: pagamentoId, produtor_id: produtorId})
    });
    const d = await r.json();
    if (!d.sucesso) return;

    const rec = d.recibo;
    let html = `
      <div class="recibo-empresa">
        <div class="nome">${rec.config?.nome_empresa || 'COOPERATIVA AGRÍCOLA COPAR'}</div>
        <div class="info">CNPJ: ${rec.config?.cnpj_empresa || '---'}</div>
        <div class="info">${rec.config?.endereco_empresa || ''}</div>
        <div class="info">${rec.config?.telefone_empresa || ''}</div>
      </div>

      <div class="recibo-linha"><strong>RECIBO Nº</strong><span>REC-${String(pagamentoId).padStart(5,'0')}</span></div>
      <div class="recibo-linha"><strong>Data</strong><span>${rec.pagamento.data}</span></div>
      <div class="recibo-linha"><strong>Produtor</strong><span>${rec.produtor.nome}</span></div>
      <div class="recibo-linha"><strong>Matrícula</strong><span>${rec.produtor.matricula}</span></div>
      <div class="recibo-linha"><strong>CPF</strong><span>${rec.produtor.cpf || '---'}</span></div>
      <div style="height:.75rem"></div>
    `;

    if (rec.vendas && rec.vendas.length) {
      html += `<div style="font-weight:700;margin:.5rem 0;font-size:.85rem">VENDAS QUITADAS</div>`;
      rec.vendas.forEach(v => {
        html += `
          <div class="recibo-linha" style="font-size:.8rem">
            <span>#${v.id} - ${v.data} - ${v.classe}</span>
            <span>${fmtKg(v.peso)}</span>
            <span>${fmt(v.pago)}</span>
          </div>
        `;
        if (v.comissao > 0) {
          html += `<div class="recibo-linha"><span class="desc-extra">Comissão COPAR descontada</span><span class="desc">-${fmt(v.comissao)}</span></div>`;
        }
        if (v.extra > 0) {
          html += `<div class="recibo-linha"><span class="desc-extra">Descontos extras</span><span class="desc">-${fmt(v.extra)}</span></div>`;
        }
      });
    }

    html += `
      <div style="height:.75rem"></div>
      <div class="recibo-linha"><strong>Forma de Pagamento</strong><span>${rec.pagamento.forma}</span></div>
      <div class="recibo-linha total"><strong>VALOR PAGO</strong><span>${fmt(rec.pagamento.valor)}</span></div>
    `;

    if (rec.pagamento.obs) {
      html += `<div class="recibo-linha" style="margin-top:.5rem"><strong>Obs</strong><span>${rec.pagamento.obs}</span></div>`;
    }

    html += `<div style="margin-top:1.5rem;padding-top:1rem;border-top:1px dashed var(--gray-300);text-align:center;font-size:.72rem;color:var(--gray-500)">
      Documento gerado eletronicamente pelo sistema COPAR Web
    </div>`;

    document.getElementById('reciboBody').innerHTML = html;
    document.getElementById('modalRecibo').classList.add('open');
  } catch(e) { console.error(e); }
}

function fecharModal() { document.getElementById('modalRecibo').classList.remove('open'); }

function imprimirRecibo() {
  const c = document.getElementById('reciboBody').innerHTML;
  const w = window.open('', '_blank');
  w.document.write(`<html><head><title>Recibo COPAR</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
      body{font-family:'Inter',sans-serif;padding:2rem;max-width:600px;margin:0 auto;font-size:.85rem}
      .recibo-empresa{text-align:center;padding-bottom:1rem;border-bottom:2px solid #0a3d2c;margin-bottom:1rem}
      .recibo-empresa .nome{font-size:1.1rem;font-weight:800;color:#0a3d2c}
      .recibo-empresa .info{font-size:.75rem;color:#6b7280}
      .recibo-linha{display:flex;justify-content:space-between;padding:.35rem 0;font-size:.82rem;border-bottom:1px dashed #e5e7eb}
      .recibo-linha.total{border-top:2px solid #0a3d2c;border-bottom:none;margin-top:.5rem;padding-top:.75rem;font-weight:700;font-size:1rem}
      .desc{color:#92400e;font-size:.78rem}
      .desc-extra{color:#6b7280;font-size:.72rem;padding-left:1rem}
    </style></head><body>${c}</body></html>`);
  w.print();
}
</script>
</body>
</html>"""


def registrar_rotas_pagamentos(app):

    @app.route('/pagamentos')
    def pagamentos():
        if not verificar_acesso():
            return "Acesso negado", 403
        return render_template_string(HTML_PAGAMENTOS, formas=FORMAS_PAGAMENTO)

    @app.route('/api/pagamentos/buscar-produtor', methods=['POST'])
    def api_bp():
        if not verificar_acesso():
            return jsonify({'encontrado': False}), 403
        d = request.get_json()
        p = buscar_produtor_por_matricula(d.get('matricula', ''))
        if not p:
            return jsonify({'encontrado': False})
        vendas = buscar_vendas_pendentes(p['id'])
        return jsonify({'encontrado': True, 'produtor': p,
                        'saldo_total': sum(v['saldo'] for v in vendas)})

    @app.route('/api/pagamentos/vendas-pendentes', methods=['POST'])
    def api_vp():
        if not verificar_acesso():
            return jsonify({'vendas': []}), 403
        d = request.get_json()
        return jsonify({'vendas': buscar_vendas_pendentes(d.get('produtor_id'))})

    @app.route('/api/pagamentos/simular', methods=['POST'])
    def api_sim():
        if not verificar_acesso():
            return jsonify({}), 403
        d = request.get_json()
        r = simular_pagamento(d.get('produtor_id'), d.get('vendas_ids', []))
        return jsonify(r or {})

    @app.route('/api/pagamentos/registrar', methods=['POST'])
    def api_reg():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(registrar_pagamento(
            d.get('produtor_id'), d.get('vendas_ids', []),
            float(d.get('valor_pago', 0)), d.get('forma_pagamento', ''),
            d.get('observacao', '')
        ))

    @app.route('/api/pagamentos/adiantar', methods=['POST'])
    def api_ad():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(registrar_adiantamento(
            d.get('produtor_id'), float(d.get('valor', 0)),
            d.get('forma_pagamento', ''), d.get('observacao', '')
        ))

    @app.route('/api/pagamentos/recibo', methods=['POST'])
    def api_rec():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        r = gerar_recibo(d.get('produtor_id'), d.get('pagamento_id'))
        if not r:
            return jsonify({'sucesso': False})
        return jsonify({'sucesso': True, 'recibo': r})

    print("✅ Módulo de Pagamentos v2 carregado!")
