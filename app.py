#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web — app.py completo e corrigido
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'copar-secret-key-2024')
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'
)

# ── Mapeamentos ───────────────────────────────────────────────────────────────

MAPEAMENTO_LOCAL = {
    'Classificação':  'Classificação',
    'classificacao':  'Classificação',
    'banca':          'Banca',
    'Banca':          'Banca',
    'toletagem':      'Toletagem',
    'Toletagem':      'Toletagem',
}

CLASSES_MAP = {
    'INDÚSTRIA': 'Indústria',
    'TIPO 2':    'Classe 2',
    'TIPO 3':    'Classe 3',
    'TIPO 4':    'Classe 4',
    'TIPO 5':    'Classe 5',
    'TIPO 6':    'Classe 6',
    'TIPO 7':    'Classe 7',
}

CLASSES_MAP_INV = {v: k for k, v in CLASSES_MAP.items()}

VALOR_HORA_BANCA = 16.00

# ── Usuários especiais ────────────────────────────────────────────────────────

USUARIOS_ESPECIAIS = {
    'copar10entrada':   {'id': 9991, 'nome': 'Setor Classificação',     'tipo': 'classificacao'},
    'copar22banca':     {'id': 9992, 'nome': 'Setor Banca',             'tipo': 'banca'},
    'copar33toletagem': {'id': 9993, 'nome': 'Setor Toletagem',         'tipo': 'toletagem'},
    'glh':              {'id': 8888, 'nome': 'Luis Henrique – Gerente', 'tipo': 'gerente'},
    'copar10':          {'id': 9999, 'nome': 'Super Administrador',     'tipo': 'superadmin'},
}


# ─────────────────────────────────────────────────────────────────────────────
#  BANCO
# ─────────────────────────────────────────────────────────────────────────────

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return None


def criar_tabela_perdas():
    conn = conectar_banco()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS perdas (
                id           SERIAL PRIMARY KEY,
                produtor_id  INTEGER REFERENCES produtores(id),
                tipo_alho    VARCHAR(50),
                classe       VARCHAR(20),
                peso_kg      DECIMAL(10,4),
                local_origem VARCHAR(30),
                data_perda   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                motivo       TEXT
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao criar tabela perdas: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  AUTENTICAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def buscar_produtor_por_matricula(matricula: str):
    chave = matricula.strip().lower()
    if chave in USUARIOS_ESPECIAIS:
        u = USUARIOS_ESPECIAIS[chave]
        return {'id': u['id'], 'nome': u['nome'], 'matricula': matricula,
                'especial': True, 'tipo': u['tipo']}

    conn = conectar_banco()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, nome, matricula FROM produtores WHERE matricula = %s",
            (matricula.strip(),)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return {'id': row[0], 'nome': row[1], 'matricula': row[2],
                    'especial': False, 'tipo': 'produtor'}
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  CONSULTAS — PRODUTOR
# ─────────────────────────────────────────────────────────────────────────────

def buscar_estoque(produtor_id):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tipo_alho, classe, SUM(peso) AS total_peso
            FROM estoque
            WHERE produtor_id = %s AND peso > 0
            GROUP BY tipo_alho, classe
            ORDER BY tipo_alho, classe
        """, (produtor_id,))
        result = [{'tipo': r[0], 'classe': r[1], 'peso': float(r[2])}
                  for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque: {e}")
        return []


def buscar_vendas(produtor_id):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento,
                   COALESCE(cp.saldo, 0)
            FROM vendas v
            LEFT JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s
            ORDER BY v.data_venda DESC
        """, (produtor_id,))
        vendas = []
        for row in cursor.fetchall():
            vendas.append({
                'id':             row[0],
                'data':           row[1].strftime('%d/%m/%Y') if row[1] else '',
                'tipo':           row[2],
                'classe':         row[3],
                'peso':           float(row[4]),
                'valor_total':    float(row[5]),
                'valor_produtor': float(row[6]),
                'status':         row[7],
                'saldo':          float(row[8]),
            })
        cursor.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas: {e}")
        return []


def calcular_saldos(vendas):
    total_recebido  = sum(v['valor_produtor'] for v in vendas if v['status'] == 'Pago')
    total_a_receber = sum(v['saldo']          for v in vendas if v['status'] != 'Pago')
    return total_recebido, total_a_receber


def buscar_produtores_por_termo(termo):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT matricula, nome, id
            FROM produtores
            WHERE matricula ILIKE %s OR nome ILIKE %s
            ORDER BY nome
            LIMIT 20
        """, (f'%{termo}%', f'%{termo}%'))
        result = [{'matricula': r[0], 'nome': r[1], 'id': r[2]}
                  for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar produtores: {e}")
        return []


def obter_saldo_estoque(produtor_id, tipo_alho, classe, local):
    conn = conectar_banco()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        local_banco = MAPEAMENTO_LOCAL.get(local, local)
        cursor.execute("""
            SELECT COALESCE(SUM(peso), 0)
            FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
              AND local_estoque = %s AND peso > 0
        """, (produtor_id, tipo_alho, classe, local_banco))
        saldo = float(cursor.fetchone()[0])
        cursor.close()
        conn.close()
        return saldo
    except Exception as e:
        logger.error(f"Erro ao obter saldo: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
#  MOVIMENTAÇÃO DE ESTOQUE
# ─────────────────────────────────────────────────────────────────────────────

def registrar_movimentacao(cursor, produtor_id, tipo_alho, classe_banco,
                            peso, local_destino, horas_banca=0,
                            local_origem=None):
    """
    Registra UMA classe dentro de uma transação já aberta pelo chamador.
    peso : kg que VAI ENTRAR no destino
    local_origem : se informado, retira `peso` da origem via FIFO com FOR UPDATE
    """
    local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)

    if local_origem:
        local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)

        cursor.execute("""
            SELECT id, peso FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
              AND local_estoque = %s AND peso > 0
            ORDER BY data_registro
            FOR UPDATE
        """, (produtor_id, tipo_alho, classe_banco, local_origem_banco))
        entradas = cursor.fetchall()

        saldo = sum(float(e[1]) for e in entradas)
        if saldo < peso - 0.001:
            raise ValueError(
                f"Saldo insuficiente em {local_origem_banco} para {classe_banco}. "
                f"Disponível: {saldo:.3f} kg, necessário: {peso:.3f} kg"
            )

        restante = peso
        for eid, epeso in entradas:
            if restante <= 0.001:
                break
            epeso = float(epeso)
            if restante >= epeso - 0.001:
                cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
                restante -= epeso
            else:
                cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                               (round(epeso - restante, 4), eid))
                restante = 0

    entrada_id = None
    if peso > 0.001:
        cursor.execute("""
            INSERT INTO estoque
                (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (produtor_id, tipo_alho, classe_banco, round(peso, 4),
              local_destino_banco, horas_banca))
        entrada_id = cursor.fetchone()[0]

    return entrada_id


def registrar_perda_por_classe(cursor, produtor_id, tipo_alho, classe_ui,
                                peso_perda, local_origem):
    """
    Remove peso_perda kg de uma classe específica da origem (FIFO dentro da classe)
    e registra como perda na tabela perdas.
    """
    local_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
    classe_banco = CLASSES_MAP.get(classe_ui, classe_ui)

    cursor.execute("""
        SELECT id, peso FROM estoque
        WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
          AND local_estoque = %s AND peso > 0
        ORDER BY data_registro
        FOR UPDATE
    """, (produtor_id, tipo_alho, classe_banco, local_banco))
    entradas = cursor.fetchall()

    saldo = sum(float(e[1]) for e in entradas)
    if saldo < peso_perda - 0.001:
        raise ValueError(
            f"Saldo insuficiente em {local_banco} para a classe {classe_ui}. "
            f"Disponível: {saldo:.3f} kg, perda: {peso_perda:.3f} kg"
        )

    restante = peso_perda
    for eid, epeso in entradas:
        if restante <= 0.001:
            break
        epeso = float(epeso)
        if restante >= epeso - 0.001:
            cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
            restante -= epeso
        else:
            cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                           (round(epeso - restante, 4), eid))
            restante = 0

    # Registra a perda na tabela perdas
    cursor.execute("""
        INSERT INTO perdas (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (produtor_id, tipo_alho, classe_banco, round(peso_perda, 4),
          local_banco, 'Perda por classe na movimentação'))


# ─────────────────────────────────────────────────────────────────────────────
#  CONSULTAS — GERENTE
# ─────────────────────────────────────────────────────────────────────────────

def obter_estatisticas_gerais():
    conn = conectar_banco()
    if not conn:
        return {k: 0 for k in ('total_produtores','total_estoque_kg',
                                'estoque_classificacao','estoque_banca','estoque_toletagem',
                                'vendas_mes','pagamentos_mes','saldo_total','perdas_mes')}
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM produtores")
        total_produtores = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE peso > 0")
        total_estoque_kg = float(cursor.fetchone()[0])

        for local in ('Classificação', 'Banca', 'Toletagem'):
            cursor.execute(
                "SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque=%s AND peso>0",
                (local,))
            key = f'estoque_{local.lower().replace("ã","a").replace("ç","c")}'
            locals()[key] = float(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM vendas
            WHERE DATE_TRUNC('month', data_venda) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        vendas_mes = float(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM pagamentos
            WHERE DATE_TRUNC('month', data_pagamento) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        pagamentos_mes = float(cursor.fetchone()[0])

        cursor.execute("SELECT COALESCE(SUM(saldo),0) FROM creditos_produtor")
        saldo_total = float(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COALESCE(SUM(peso_kg),0) FROM perdas
            WHERE DATE_TRUNC('month', data_perda) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        perdas_mes = float(cursor.fetchone()[0])

        # Re‑fetch for explicit variables (avoid locals() confusion)
        cursor.execute(
            "SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Classificação' AND peso>0")
        estoque_classificacao = float(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Banca' AND peso>0")
        estoque_banca = float(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Toletagem' AND peso>0")
        estoque_toletagem = float(cursor.fetchone()[0])

        cursor.close()
        conn.close()

        return {
            'total_produtores':     total_produtores,
            'total_estoque_kg':     total_estoque_kg,
            'estoque_classificacao': estoque_classificacao,
            'estoque_banca':         estoque_banca,
            'estoque_toletagem':     estoque_toletagem,
            'vendas_mes':            vendas_mes,
            'pagamentos_mes':        pagamentos_mes,
            'saldo_total':           saldo_total,
            'perdas_mes':            perdas_mes,
        }
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        return {k: 0 for k in ('total_produtores','total_estoque_kg',
                                'estoque_classificacao','estoque_banca','estoque_toletagem',
                                'vendas_mes','pagamentos_mes','saldo_total','perdas_mes')}


def obter_estoque_hierarquico():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.local_estoque, e.tipo_alho, e.classe,
                   p.nome AS produtor,
                   SUM(e.peso)                   AS total_peso,
                   COALESCE(SUM(e.horas_banca),0) AS total_horas
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.peso > 0
            GROUP BY e.local_estoque, e.tipo_alho, e.classe, p.nome
            ORDER BY e.local_estoque, e.tipo_alho, e.classe, p.nome
        """)

        hierarquia = {}
        for row in cursor.fetchall():
            local, tipo, classe, produtor = row[0], row[1], row[2], row[3]
            peso, horas = float(row[4]), float(row[5])
            hierarquia.setdefault(local, {}).setdefault(tipo, {}).setdefault(classe, [])
            hierarquia[local][tipo][classe].append(
                {'produtor': produtor, 'peso': peso, 'horas': horas}
            )

        cursor.close()
        conn.close()

        resultado = []
        for local, tipos in hierarquia.items():
            local_item = {'local': local, 'tipos': []}
            for tipo, classes in tipos.items():
                tipo_item = {'tipo': tipo, 'classes': []}
                for classe, produtores in classes.items():
                    tipo_item['classes'].append({
                        'classe':      classe,
                        'total_peso':  sum(p['peso']  for p in produtores),
                        'total_horas': sum(p['horas'] for p in produtores),
                        'produtores':  produtores,
                    })
                local_item['tipos'].append(tipo_item)
            resultado.append(local_item)

        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar estoque hierárquico: {e}")
        return []


def obter_estoque_por_produtor():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.nome, e.tipo_alho, e.classe,
                   e.local_estoque, SUM(e.peso) AS total_peso
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.peso > 0
            GROUP BY p.nome, e.tipo_alho, e.classe, e.local_estoque
            ORDER BY p.nome, e.tipo_alho
        """)
        result = [
            {'produtor': r[0], 'tipo': r[1], 'classe': r[2],
             'local': r[3], 'peso': float(r[4])}
            for r in cursor.fetchall()
        ]
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque por produtor: {e}")
        return []


def obter_vendas_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, p.nome, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento, v.data_venda
            FROM vendas v
            JOIN produtores p ON v.produtor_id = p.id
            WHERE DATE_TRUNC('month', v.data_venda) = DATE_TRUNC('month', CURRENT_DATE)
            ORDER BY v.data_venda DESC
            LIMIT %s
        """, (limite,))
        vendas = []
        for r in cursor.fetchall():
            vendas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'valor_total': float(r[5]),
                'valor_produtor': float(r[6]), 'status': r[7],
                'data': r[8].strftime('%d/%m/%Y') if r[8] else '',
            })
        cursor.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas recentes: {e}")
        return []


def obter_pagamentos_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pa.id, p.nome, pa.valor_total, pa.forma_pagamento, pa.data_pagamento
            FROM pagamentos pa
            JOIN produtores p ON pa.produtor_id = p.id
            WHERE DATE_TRUNC('month', pa.data_pagamento) = DATE_TRUNC('month', CURRENT_DATE)
            ORDER BY pa.data_pagamento DESC
            LIMIT %s
        """, (limite,))
        pagamentos = []
        for r in cursor.fetchall():
            pagamentos.append({
                'id': r[0], 'produtor': r[1], 'valor': float(r[2]),
                'forma': r[3], 'data': r[4].strftime('%d/%m/%Y') if r[4] else '',
            })
        cursor.close()
        conn.close()
        return pagamentos
    except Exception as e:
        logger.error(f"Erro ao buscar pagamentos recentes: {e}")
        return []


def obter_estoque_por_tipo():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tipo_alho, COALESCE(SUM(peso),0) AS total_peso
            FROM estoque WHERE peso > 0
            GROUP BY tipo_alho ORDER BY total_peso DESC
        """)
        result = [{'tipo': r[0], 'peso': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque por tipo: {e}")
        return []


def obter_vendas_por_mes():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', data_venda), 'Mon/YYYY') AS mes,
                   COALESCE(SUM(valor_total),0) AS total_vendas
            FROM vendas
            WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', data_venda)
            ORDER BY DATE_TRUNC('month', data_venda)
        """)
        result = [{'mes': r[0], 'total': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar vendas por mês: {e}")
        return []


def obter_perdas_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, pr.nome, p.tipo_alho, p.classe, p.peso_kg,
                   p.local_origem, p.data_perda, p.motivo
            FROM perdas p
            JOIN produtores pr ON p.produtor_id = pr.id
            WHERE DATE_TRUNC('month', p.data_perda) = DATE_TRUNC('month', CURRENT_DATE)
            ORDER BY p.data_perda DESC
            LIMIT %s
        """, (limite,))
        perdas = []
        for r in cursor.fetchall():
            perdas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'local_origem': r[5],
                'data': r[6].strftime('%d/%m/%Y') if r[6] else '',
                'motivo': r[7] or '',
            })
        cursor.close()
        conn.close()
        return perdas
    except Exception as e:
        logger.error(f"Erro ao buscar perdas recentes: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  ROTAS
# ─────────────────────────────────────────────────────────────────────────────

def _redirecionar_por_tipo(tipo):
    if tipo == 'gerente':
        return redirect(url_for('gerente'))
    if tipo in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return redirect(url_for('registro_entrada'))
    return redirect(url_for('produtor'))


@app.route('/')
def index():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    return _redirecionar_por_tipo(session.get('tipo'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'produtor_id' in session:
        return _redirecionar_por_tipo(session.get('tipo'))

    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        if not matricula:
            return render_template('login.html', erro='Digite sua matrícula')

        produtor = buscar_produtor_por_matricula(matricula)
        if produtor:
            session.permanent = True
            session['produtor_id']        = produtor['id']
            session['produtor_nome']      = produtor['nome']
            session['produtor_matricula'] = produtor['matricula']
            session['acesso_especial']    = produtor.get('especial', False)
            session['tipo']               = produtor.get('tipo', 'produtor')
            return _redirecionar_por_tipo(session['tipo'])

        return render_template('login.html', erro='Matrícula não encontrada')

    return render_template('login.html', erro=None)


@app.route('/produtor')
def produtor():
    if 'produtor_id' not in session or session.get('tipo') not in (None, 'produtor'):
        return redirect(url_for('login'))
    pid  = session['produtor_id']
    nome = session['produtor_nome']
    estoque = buscar_estoque(pid)
    vendas  = buscar_vendas(pid)
    total_recebido, total_a_receber = calcular_saldos(vendas)
    return render_template('produtor.html',
                           nome=nome, estoque=estoque, vendas=vendas,
                           total_recebido=total_recebido,
                           total_a_receber=total_a_receber)


@app.route('/registro-entrada')
def registro_entrada():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    tipo = session.get('tipo')
    if tipo not in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return redirect(url_for('produtor'))
    return render_template('registro_entrada.html',
                           role=tipo,
                           valor_hora_banca=VALOR_HORA_BANCA)


@app.route('/gerente')
def gerente():
    if 'produtor_id' not in session or session.get('tipo') != 'gerente':
        return redirect(url_for('login'))
    return render_template('gerente.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────────────────────
#  APIs — GERAIS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/buscar-produtores', methods=['GET'])
def api_buscar_produtores():
    termo = request.args.get('termo', '').strip()
    if len(termo) < 2:
        return jsonify([])
    return jsonify(buscar_produtores_por_termo(termo))


@app.route('/api/obter-saldo', methods=['POST'])
def api_obter_saldo():
    data        = request.get_json(silent=True) or {}
    produtor_id = data.get('produtor_id')
    tipo_alho   = data.get('tipo_alho')
    classe      = data.get('classe')
    local       = data.get('local')
    if not all([produtor_id, tipo_alho, classe, local]):
        return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos', 'saldo': 0})
    saldo = obter_saldo_estoque(produtor_id, tipo_alho, classe, local)
    return jsonify({'sucesso': True, 'saldo': saldo})


@app.route('/api/obter-saldos-todos', methods=['POST'])
def api_obter_saldos_todos():
    data        = request.get_json(silent=True) or {}
    produtor_id = data.get('produtor_id')
    tipo_alho   = data.get('tipo_alho')
    local       = data.get('local')

    if not all([produtor_id, tipo_alho, local]):
        return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos', 'saldos': {}})

    local_banco = MAPEAMENTO_LOCAL.get(local, local)

    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão', 'saldos': {}})

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT classe, COALESCE(SUM(peso), 0)
            FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND local_estoque = %s AND peso > 0
            GROUP BY classe
        """, (produtor_id, tipo_alho, local_banco))

        saldos = {}
        for row in cursor.fetchall():
            classe_ui = CLASSES_MAP_INV.get(row[0], row[0])
            saldos[classe_ui] = float(row[1])

        cursor.close()
        conn.close()
        return jsonify({'sucesso': True, 'saldos': saldos})

    except Exception as e:
        logger.error(f"Erro ao buscar saldos em lote: {e}")
        if conn:
            conn.close()
        return jsonify({'sucesso': False, 'mensagem': str(e), 'saldos': {}})


@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """
    Payload:
    {
        "produtor_id":  123,
        "tipo_alho":    "São Valentim",
        "local":        "banca",
        "local_origem": "Classificação",
        "horas_banca":  2,
        "detalhes": [
            { "classe": "TIPO 2",     "peso": 500, "tipo": "classe"    },
            { "classe": "INDÚSTRIA",  "peso":  80, "tipo": "industria" },
            { "classe": "TIPO 2",     "peso":   2, "tipo": "perda"     }
        ]
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400

    role = session.get('tipo')
    if role not in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado'}), 403

    produtor_id   = data.get('produtor_id')
    tipo_alho     = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem  = data.get('local_origem')
    detalhes      = data.get('detalhes', [])
    horas_banca   = float(data.get('horas_banca', 0) or 0)

    # Validações básicas
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})

    # Validações por role
    if role == 'classificacao':
        if local_destino != 'Classificação':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Classificação só registra entrada inicial.'})
        local_origem = None
        if horas_banca > 0:
            return jsonify({'sucesso': False, 'mensagem': 'Classificação não permite horas de banca.'})
    elif role == 'banca':
        if local_destino != 'banca':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Banca só transfere para Banca.'})
        if not local_origem or local_origem not in ('Classificação', 'Toletagem'):
            return jsonify({'sucesso': False, 'mensagem': 'Para Banca, a origem deve ser Classificação ou Toletagem.'})
    elif role == 'toletagem':
        if local_destino != 'toletagem':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Toletagem só transfere para Toletagem.'})
        if not local_origem or local_origem not in ('Classificação', 'Banca'):
            return jsonify({'sucesso': False, 'mensagem': 'Para Toletagem, a origem deve ser Classificação ou Banca.'})

    # Separação dos itens
    itens_destino = [d for d in detalhes if d.get('tipo') in ('classe', 'industria')]
    itens_perda   = [d for d in detalhes if d.get('tipo') == 'perda']

    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão com o banco'}), 500

    try:
        cursor = conn.cursor()
        resultados = []
        total_entrou_destino = 0
        total_saiu_origem    = 0

        # Processar itens que vão para o destino
        for item in itens_destino:
            classe_ui = item.get('classe')
            peso      = float(item.get('peso', 0) or 0)
            if peso <= 0:
                continue

            if classe_ui == 'INDÚSTRIA':
                classe_banco = 'Indústria'
            else:
                classe_banco = CLASSES_MAP.get(classe_ui)
            if not classe_banco:
                raise ValueError(f'Classe "{classe_ui}" não reconhecida')

            entrada_id = registrar_movimentacao(
                cursor        = cursor,
                produtor_id   = produtor_id,
                tipo_alho     = tipo_alho,
                classe_banco  = classe_banco,
                peso          = peso,
                local_destino = local_destino,
                horas_banca   = horas_banca,
                local_origem  = local_origem,
            )
            resultados.append({'classe': classe_ui, 'peso': peso, 'entrada_id': entrada_id})
            total_entrou_destino += peso
            total_saiu_origem    += peso

        # Processar perdas por classe
        for item in itens_perda:
            classe_ui = item.get('classe')
            peso      = float(item.get('peso', 0) or 0)
            if peso <= 0:
                continue
            registrar_perda_por_classe(
                cursor        = cursor,
                produtor_id   = produtor_id,
                tipo_alho     = tipo_alho,
                classe_ui     = classe_ui,
                peso_perda    = peso,
                local_origem  = local_origem,
            )
            resultados.append({'classe': classe_ui, 'peso': peso, 'tipo': 'perda'})
            total_saiu_origem += peso

        conn.commit()
        cursor.close()
        conn.close()

        msg = f'Registrado com sucesso! Entrou no destino: {total_entrou_destino:.2f} kg'
        if itens_perda:
            msg += f' | Perdas registradas: {sum(p["peso"] for p in itens_perda):.2f} kg'
        if horas_banca > 0:
            msg += f' | Horas: {horas_banca}'
        if local_origem:
            msg += f' | Origem: {local_origem}'

        return jsonify({'sucesso': True, 'mensagem': msg, 'registros': resultados})

    except ValueError as e:
        conn.rollback()
        conn.close()
        logger.warning(f"Validação em salvar-entrada: {e}")
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 400

    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro em salvar-entrada: {e}")
        return jsonify({'sucesso': False, 'mensagem': f'Erro interno: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  APIs — GERENTE
# ─────────────────────────────────────────────────────────────────────────────

def _requer_gerente():
    return 'produtor_id' not in session or session.get('tipo') != 'gerente'


@app.route('/api/gerente/estatisticas')
def api_gerente_estatisticas():
    if _requer_gerente():
        return jsonify({}), 403
    return jsonify(obter_estatisticas_gerais())


@app.route('/api/gerente/estoque-hierarquico')
def api_gerente_estoque_hierarquico():
    if _requer_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_hierarquico())


@app.route('/api/gerente/estoque-produtor')
def api_gerente_estoque_produtor():
    if _requer_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_por_produtor())


@app.route('/api/gerente/vendas-recentes')
def api_gerente_vendas_recentes():
    if _requer_gerente():
        return jsonify([]), 403
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_vendas_recentes(limite))


@app.route('/api/gerente/pagamentos-recentes')
def api_gerente_pagamentos_recentes():
    if _requer_gerente():
        return jsonify([]), 403
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_pagamentos_recentes(limite))


@app.route('/api/gerente/estoque-por-tipo')
def api_gerente_estoque_por_tipo():
    if _requer_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_por_tipo())


@app.route('/api/gerente/vendas-por-mes')
def api_gerente_vendas_por_mes():
    if _requer_gerente():
        return jsonify([]), 403
    return jsonify(obter_vendas_por_mes())


@app.route('/api/gerente/perdas-recentes')
def api_gerente_perdas_recentes():
    if _requer_gerente():
        return jsonify([]), 403
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_perdas_recentes(limite))


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    criar_tabela_perdas()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
