#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web — Versão Final
- Apenas Classificação (e SuperAdmin) podem cadastrar produtores
- Gerente tem acesso total aos relatórios
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg
import os
import logging
from datetime import timedelta, datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'copar-secret-key-2024')
app.config.update(
    SESSION_COOKIE_SECURE=False,          # Mude para True em produção HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'
)

# ─── Mapeamentos ─────────────────────────────────────────────────────────────
MAPEAMENTO_LOCAL = {
    'Classificação': 'Classificação',
    'classificacao': 'Classificação',
    'banca': 'Banca',
    'Banca': 'Banca',
    'toletagem': 'Toletagem',
    'Toletagem': 'Toletagem',
}

CLASSES_MAP = {
    'INDÚSTRIA': 'Indústria',
    'TIPO 2': 'Classe 2',
    'TIPO 3': 'Classe 3',
    'TIPO 4': 'Classe 4',
    'TIPO 5': 'Classe 5',
    'TIPO 6': 'Classe 6',
    'TIPO 7': 'Classe 7',
}
CLASSES_MAP_INV = {v: k for k, v in CLASSES_MAP.items()}

VALOR_HORA_BANCA = 16.00

USUARIOS_ESPECIAIS = {
    'copar10entrada':   {'id': 9991, 'nome': 'Setor Classificação', 'tipo': 'classificacao'},
    'copar22banca':     {'id': 9992, 'nome': 'Setor Banca', 'tipo': 'banca'},
    'copar33toletagem': {'id': 9993, 'nome': 'Setor Toletagem', 'tipo': 'toletagem'},
    'glh':              {'id': 8888, 'nome': 'Luis Henrique – Gerente', 'tipo': 'gerente'},
    'copar10':          {'id': 9999, 'nome': 'Super Administrador', 'tipo': 'superadmin'},
}

# ─── Banco de dados ─────────────────────────────────────────────────────────
def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return None

def criar_tabelas():
    conn = conectar_banco()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # Tabela produtores com CPF e senha
        cur.execute("""
            CREATE TABLE IF NOT EXISTS produtores (
                id SERIAL PRIMARY KEY,
                matricula VARCHAR(20) UNIQUE NOT NULL,
                nome VARCHAR(100) NOT NULL,
                cpf VARCHAR(14),
                senha VARCHAR(10)
            )
        """)
        # Tabela estoque
        cur.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id) ON DELETE CASCADE,
                tipo_alho VARCHAR(50),
                classe VARCHAR(20),
                peso DECIMAL(10,4),
                local_estoque VARCHAR(30),
                horas_banca DECIMAL(10,2) DEFAULT 0,
                data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Tabela vendas
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vendas (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id) ON DELETE CASCADE,
                data_venda TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo_alho VARCHAR(50),
                classe VARCHAR(20),
                peso DECIMAL(10,4),
                valor_total DECIMAL(10,2),
                valor_produtor DECIMAL(10,2),
                status_pagamento VARCHAR(20) DEFAULT 'Pendente'
            )
        """)
        # Tabela pagamentos
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pagamentos (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id) ON DELETE CASCADE,
                valor_total DECIMAL(10,2),
                forma_pagamento VARCHAR(50),
                data_pagamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Tabela creditos_produtor
        cur.execute("""
            CREATE TABLE IF NOT EXISTS creditos_produtor (
                id SERIAL PRIMARY KEY,
                venda_id INTEGER REFERENCES vendas(id) ON DELETE CASCADE,
                saldo DECIMAL(10,2) DEFAULT 0
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Tabelas criadas/verificadas com sucesso")
    except Exception as e:
        logger.error(f"Erro ao criar tabelas: {e}")

# ─── Autenticação e permissões ──────────────────────────────────────────────
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
        cur = conn.cursor()
        cur.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s",
                    (matricula.strip(),))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {'id': row[0], 'nome': row[1], 'matricula': row[2],
                    'especial': False, 'tipo': 'produtor'}
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

# Funções de autorização
def _check_gerente():
    """Apenas gerente tem acesso"""
    return 'produtor_id' not in session or session.get('tipo') != 'gerente'

def _check_classificacao():
    """Apenas classificação e superadmin podem cadastrar produtores"""
    if 'produtor_id' not in session:
        return True
    tipo = session.get('tipo')
    return tipo not in ('classificacao', 'superadmin')   # só classificação e superadmin

# ─── CRUD de Produtores (apenas classificação) ──────────────────────────────
def validar_cpf(cpf):
    cpf = ''.join(filter(str.isdigit, cpf))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    dig1 = 11 - (soma % 11)
    if dig1 >= 10:
        dig1 = 0
    if dig1 != int(cpf[9]):
        return False
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    dig2 = 11 - (soma % 11)
    if dig2 >= 10:
        dig2 = 0
    return dig2 == int(cpf[10])

def gerar_senha(cpf):
    cpf_clean = ''.join(filter(str.isdigit, cpf))
    return cpf_clean[-2:] if len(cpf_clean) >= 11 else "00"

def cadastrar_produtor(nome, cpf, matricula):
    if not nome or not cpf or not matricula:
        return {'sucesso': False, 'mensagem': 'Todos os campos são obrigatórios'}
    if not validar_cpf(cpf):
        return {'sucesso': False, 'mensagem': 'CPF inválido'}
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM produtores WHERE matricula = %s", (matricula,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return {'sucesso': False, 'mensagem': 'Matrícula já cadastrada'}
        cur.execute("""
            INSERT INTO produtores (nome, matricula, cpf, senha)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (nome, matricula, cpf, gerar_senha(cpf)))
        produtor_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {
            'sucesso': True,
            'mensagem': f'Produtor {nome} cadastrado com sucesso!',
            'produtor_id': produtor_id,
            'senha': gerar_senha(cpf)
        }
    except Exception as e:
        logger.error(f"Erro ao cadastrar produtor: {e}")
        return {'sucesso': False, 'mensagem': f'Erro: {str(e)}'}

def listar_produtores():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, matricula, cpf, senha
            FROM produtores ORDER BY nome
        """)
        produtores = [{'id': r[0], 'nome': r[1], 'matricula': r[2], 'cpf': r[3], 'senha': r[4]}
                      for r in cur.fetchall()]
        cur.close()
        conn.close()
        return produtores
    except Exception as e:
        logger.error(f"Erro ao listar produtores: {e}")
        return []

# ─── Consultas do Produtor ──────────────────────────────────────────────────
def buscar_estoque(produtor_id):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tipo_alho, classe, local_estoque, SUM(peso)
            FROM estoque WHERE produtor_id = %s AND peso > 0
            GROUP BY tipo_alho, classe, local_estoque ORDER BY tipo_alho, classe
        """, (produtor_id,))
        result = []
        for r in cur.fetchall():
            local = r[2]
            result.append({
                'tipo': r[0], 'classe': r[1], 'local': local,
                'peso': float(r[3]),
                'em_progresso': local in ('Banca', 'Toletagem')
            })
        cur.close()
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
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, v.data_venda, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento,
                   COALESCE(cp.saldo, 0)
            FROM vendas v
            LEFT JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s ORDER BY v.data_venda DESC
        """, (produtor_id,))
        vendas = []
        for r in cur.fetchall():
            vendas.append({
                'id': r[0],
                'data': r[1].strftime("%d/%m/%Y") if r[1] else "",
                'tipo': r[2], 'classe': r[3],
                'peso': float(r[4]), 'valor_total': float(r[5]),
                'valor_produtor': float(r[6]), 'status': r[7],
                'saldo': float(r[8])
            })
        cur.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas: {e}")
        return []

def calcular_saldos(vendas):
    recebido = sum(v['valor_produtor'] for v in vendas if v['status'] == 'Pago')
    a_receber = sum(v['saldo'] for v in vendas if v['status'] != 'Pago')
    return recebido, a_receber

def buscar_produtores_por_termo(termo):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT matricula, nome, id FROM produtores
            WHERE matricula ILIKE %s OR nome ILIKE %s ORDER BY nome LIMIT 20
        """, (f'%{termo}%', f'%{termo}%'))
        result = [{'matricula': r[0], 'nome': r[1], 'id': r[2]} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar produtores: {e}")
        return []

# ─── Movimentação de estoque (FIFO) ─────────────────────────────────────────
def _retirar_fifo(cur, produtor_id, tipo_alho, classe_banco, local_banco, quantidade):
    cur.execute("""
        SELECT id, peso FROM estoque
        WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
          AND local_estoque = %s AND peso > 0
        ORDER BY data_registro, id FOR UPDATE
    """, (produtor_id, tipo_alho, classe_banco, local_banco))
    rows = cur.fetchall()
    saldo = sum(float(r[1]) for r in rows)
    if saldo < quantidade - 0.001:
        raise ValueError(f"Saldo insuficiente em {local_banco} para {classe_banco}. "
                         f"Disponível: {saldo:.3f} kg, necessário: {quantidade:.3f} kg")
    restante = quantidade
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

def _inserir_estoque(cur, produtor_id, tipo_alho, classe_banco, peso, local_banco, horas=0):
    cur.execute("""
        INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (produtor_id, tipo_alho, classe_banco, round(peso, 4), local_banco, horas))
    return cur.fetchone()[0]

# ─── Consultas do Gerente (relatórios) ──────────────────────────────────────
def obter_estatisticas_completas():
    conn = conectar_banco()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM produtores")
        total_produtores = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE peso > 0")
        total_estoque = float(cur.fetchone()[0])
        cur.execute("""
            SELECT local_estoque, COALESCE(SUM(peso),0)
            FROM estoque WHERE peso > 0 GROUP BY local_estoque
        """)
        estoque_por_local = {row[0]: float(row[1]) for row in cur.fetchall()}
        cur.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM vendas
            WHERE DATE_TRUNC('month', data_venda) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        vendas_mes = float(cur.fetchone()[0])
        cur.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM pagamentos
            WHERE DATE_TRUNC('month', data_pagamento) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        pagamentos_mes = float(cur.fetchone()[0])
        cur.close()
        conn.close()
        return {
            'total_produtores': total_produtores,
            'total_estoque_kg': total_estoque,
            'estoque_classificacao': estoque_por_local.get('Classificação', 0),
            'estoque_banca': estoque_por_local.get('Banca', 0),
            'estoque_toletagem': estoque_por_local.get('Toletagem', 0),
            'vendas_mes': vendas_mes,
            'pagamentos_mes': pagamentos_mes,
            'perdas_mes': 0
        }
    except Exception as e:
        logger.error(f"Erro estatísticas: {e}")
        return {}

def obter_estoque_por_tipo():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tipo_alho, COALESCE(SUM(peso),0)
            FROM estoque WHERE peso > 0 GROUP BY tipo_alho ORDER BY SUM(peso) DESC
        """)
        result = [{'tipo': row[0] or 'Não definido', 'peso': float(row[1])} for row in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro estoque por tipo: {e}")
        return []

def obter_vendas_por_mes():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', data_venda), 'Mon/YYYY') as mes,
                   COALESCE(SUM(valor_total),0) as total
            FROM vendas WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', data_venda) ORDER BY DATE_TRUNC('month', data_venda)
        """)
        result = [{'mes': row[0], 'total': float(row[1])} for row in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro vendas por mês: {e}")
        return []

def obter_vendas_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, p.nome, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento, v.data_venda
            FROM vendas v JOIN produtores p ON v.produtor_id = p.id
            ORDER BY v.data_venda DESC LIMIT %s
        """, (limite,))
        rows = []
        for r in cur.fetchall():
            rows.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'valor_total': float(r[5]), 'valor_produtor': float(r[6]),
                'status': r[7], 'data': r[8].strftime("%d/%m/%Y %H:%M") if r[8] else ""
            })
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Erro vendas recentes: {e}")
        return []

def obter_pagamentos_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, prod.nome, p.valor_total, p.forma_pagamento, p.data_pagamento
            FROM pagamentos p JOIN produtores prod ON p.produtor_id = prod.id
            ORDER BY p.data_pagamento DESC LIMIT %s
        """, (limite,))
        rows = []
        for r in cur.fetchall():
            rows.append({
                'id': r[0], 'produtor': r[1], 'valor': float(r[2]),
                'forma': r[3], 'data': r[4].strftime("%d/%m/%Y %H:%M") if r[4] else ""
            })
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Erro pagamentos recentes: {e}")
        return []

def obter_estoque_hierarquico():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.local_estoque, e.tipo_alho, e.classe, p.nome,
                   SUM(e.peso), COALESCE(SUM(e.horas_banca),0)
            FROM estoque e JOIN produtores p ON e.produtor_id = p.id
            WHERE e.peso > 0
            GROUP BY e.local_estoque, e.tipo_alho, e.classe, p.nome
            ORDER BY e.local_estoque, e.tipo_alho, e.classe, p.nome
        """)
        hier = {}
        for row in cur.fetchall():
            local, tipo, classe, prod = row[0], row[1], row[2], row[3]
            peso, horas = float(row[4]), float(row[5])
            hier.setdefault(local, {}).setdefault(tipo, {}).setdefault(classe, []).append({
                'produtor': prod, 'peso': peso, 'horas': horas
            })
        cur.close()
        conn.close()
        result = []
        for local, tipos in hier.items():
            local_data = {'local': local, 'tipos': []}
            for tipo, classes in tipos.items():
                tipo_data = {'tipo': tipo, 'classes': []}
                for classe, prods in classes.items():
                    tipo_data['classes'].append({
                        'classe': classe,
                        'total_peso': sum(p['peso'] for p in prods),
                        'total_horas': sum(p['horas'] for p in prods),
                        'produtores': prods
                    })
                local_data['tipos'].append(tipo_data)
            result.append(local_data)
        return result
    except Exception as e:
        logger.error(f"Erro estoque hierárquico: {e}")
        return []

# ─── Rotas HTML ─────────────────────────────────────────────────────────────
def _redirecionar(tipo):
    if tipo == 'gerente':
        return redirect(url_for('gerente'))
    if tipo in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return redirect(url_for('registro_entrada'))
    return redirect(url_for('produtor'))

@app.route('/')
def index():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    return _redirecionar(session.get('tipo'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'produtor_id' in session:
        return _redirecionar(session.get('tipo'))
    if request.method == 'POST':
        mat = request.form.get('matricula', '').strip()
        if not mat:
            return render_template('login.html', erro='Digite sua matrícula')
        prod = buscar_produtor_por_matricula(mat)
        if prod:
            session.permanent = True
            session.update({
                'produtor_id': prod['id'],
                'produtor_nome': prod['nome'],
                'produtor_matricula': prod['matricula'],
                'acesso_especial': prod.get('especial', False),
                'tipo': prod.get('tipo', 'produtor')
            })
            return _redirecionar(session['tipo'])
        return render_template('login.html', erro='Matrícula não encontrada')
    return render_template('login.html', erro=None)

@app.route('/produtor')
def produtor():
    if 'produtor_id' not in session or session.get('tipo') not in (None, 'produtor'):
        return redirect(url_for('login'))
    pid = session['produtor_id']
    estoque = buscar_estoque(pid)
    vendas = buscar_vendas(pid)
    recebido, a_receber = calcular_saldos(vendas)
    return render_template('produtor.html', nome=session['produtor_nome'],
                           estoque=estoque, vendas=vendas,
                           total_recebido=recebido, total_a_receber=a_receber)

@app.route('/registro-entrada')
def registro_entrada():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    tipo = session.get('tipo')
    if tipo not in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return redirect(url_for('produtor'))
    return render_template('registro_entrada.html', role=tipo,
                           valor_hora_banca=VALOR_HORA_BANCA)

@app.route('/gerente')
def gerente():
    if _check_gerente():
        return redirect(url_for('login'))
    return render_template('gerente.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── APIs de Produtores (apenas classificação e superadmin) ─────────────────
@app.route('/api/produtores/listar')
def api_produtores_listar():
    if _check_classificacao():
        return jsonify([]), 403
    return jsonify(listar_produtores())

@app.route('/api/produtores/cadastrar', methods=['POST'])
def api_produtores_cadastrar():
    if _check_classificacao():
        return jsonify({'sucesso': False, 'mensagem': 'Não autorizado'}), 403
    data = request.get_json()
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400
    result = cadastrar_produtor(
        data.get('nome', '').strip(),
        data.get('cpf', '').strip(),
        data.get('matricula', '').strip()
    )
    return jsonify(result)

# (Opcional) Editar e excluir – se quiser manter para classificação, descomente
# @app.route('/api/produtores/editar', methods=['POST'])
# def api_produtores_editar():
#     if _check_classificacao():
#         return jsonify({'sucesso': False, 'mensagem': 'Não autorizado'}), 403
#     ...

# ─── APIs do Gerente (apenas gerente) ───────────────────────────────────────
@app.route('/api/gerente/estatisticas')
def api_gerente_estatisticas():
    if _check_gerente():
        return jsonify({}), 403
    return jsonify(obter_estatisticas_completas())

@app.route('/api/gerente/estoque-por-tipo')
def api_gerente_estoque_por_tipo():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_por_tipo())

@app.route('/api/gerente/vendas-por-mes')
def api_gerente_vendas_por_mes():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_vendas_por_mes())

@app.route('/api/gerente/vendas-recentes')
def api_gerente_vendas_recentes():
    if _check_gerente():
        return jsonify([]), 403
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_vendas_recentes(limite))

@app.route('/api/gerente/pagamentos-recentes')
def api_gerente_pagamentos_recentes():
    if _check_gerente():
        return jsonify([]), 403
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_pagamentos_recentes(limite))

@app.route('/api/gerente/estoque-hierarquico')
def api_gerente_estoque_hierarquico():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_hierarquico())

# ─── APIs de movimentação de estoque ────────────────────────────────────────
@app.route('/api/buscar-produtores')
def api_buscar_produtores():
    termo = request.args.get('termo', '').strip()
    return jsonify(buscar_produtores_por_termo(termo) if len(termo) >= 1 else [])

@app.route('/api/obter-saldos-todos', methods=['POST'])
def api_obter_saldos_todos():
    d = request.get_json(silent=True) or {}
    pid = d.get('produtor_id')
    tipo_alho = d.get('tipo_alho')
    local = d.get('local')
    if not all([pid, tipo_alho, local]):
        return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos', 'saldos': {}})
    local_banco = MAPEAMENTO_LOCAL.get(local, local)
    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão', 'saldos': {}})
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT classe, COALESCE(SUM(peso),0)
            FROM estoque WHERE produtor_id=%s AND tipo_alho=%s AND local_estoque=%s AND peso>0
            GROUP BY classe
        """, (pid, tipo_alho, local_banco))
        saldos = {}
        for row in cur.fetchall():
            ui = CLASSES_MAP_INV.get(row[0])
            if ui:
                saldos[ui] = float(row[1])
        cur.close()
        conn.close()
        return jsonify({'sucesso': True, 'saldos': saldos})
    except Exception as e:
        logger.error(f"Erro saldos todos: {e}")
        conn.close()
        return jsonify({'sucesso': False, 'mensagem': str(e), 'saldos': {}})

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400
    role = session.get('tipo')
    if role not in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado'}), 403
    pid = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem = data.get('local_origem')
    detalhes = data.get('detalhes', [])
    horas_banca = float(data.get('horas_banca', 0) or 0)
    if not pid or not tipo_alho or not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Dados incompletos'}), 400
    local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)
    local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem) if local_origem else None
    # Validações por papel
    if role == 'classificacao' and local_destino_banco != 'Classificação':
        return jsonify({'sucesso': False, 'mensagem': 'Classificação só registra entrada inicial.'})
    if role == 'banca':
        if local_destino_banco != 'Banca':
            return jsonify({'sucesso': False, 'mensagem': 'Banca só transfere para Banca.'})
        if not local_origem_banco or local_origem_banco not in ('Classificação', 'Toletagem'):
            return jsonify({'sucesso': False, 'mensagem': 'Origem deve ser Classificação ou Toletagem.'})
    if role == 'toletagem':
        if local_destino_banco != 'Toletagem':
            return jsonify({'sucesso': False, 'mensagem': 'Toletagem só transfere para Toletagem.'})
        if not local_origem_banco or local_origem_banco not in ('Classificação', 'Banca'):
            return jsonify({'sucesso': False, 'mensagem': 'Origem deve ser Classificação ou Banca.'})
    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão'}), 500
    conn.autocommit = False
    try:
        cur = conn.cursor()
        total_destino = 0
        total_perdas = 0
        for item in detalhes:
            classe_ui = item.get('classe', '')
            peso = float(item.get('peso', 0) or 0)
            tipo_item = item.get('tipo', '')
            if peso <= 0.001:
                continue
            classe_banco = CLASSES_MAP.get(classe_ui)
            if not classe_banco:
                raise ValueError(f'Classe "{classe_ui}" não reconhecida')
            if tipo_item == 'entrada':
                _inserir_estoque(cur, pid, tipo_alho, classe_banco, peso, local_destino_banco, horas_banca)
                total_destino += peso
            elif tipo_item == 'transferencia':
                if not local_origem_banco:
                    raise ValueError(f'Origem não informada para transferência de {classe_ui}')
                _retirar_fifo(cur, pid, tipo_alho, classe_banco, local_origem_banco, peso)
                _inserir_estoque(cur, pid, tipo_alho, classe_banco, peso, local_destino_banco, horas_banca)
                total_destino += peso
            elif tipo_item == 'perda':
                if not local_origem_banco:
                    raise ValueError(f'Origem não informada para perda de {classe_ui}')
                _retirar_fifo(cur, pid, tipo_alho, classe_banco, local_origem_banco, peso)
                total_perdas += peso
            elif tipo_item == 'industria':
                _inserir_estoque(cur, pid, tipo_alho, classe_banco, peso, local_destino_banco, horas_banca)
                total_destino += peso
        conn.commit()
        cur.close()
        conn.close()
        msg = f'Registrado! Destino: {total_destino:.2f} kg'
        if total_perdas > 0:
            msg += f' | Perdas: {total_perdas:.2f} kg'
        if horas_banca > 0:
            msg += f' | Horas banca: {horas_banca}'
        if local_origem:
            msg += f' | Origem: {local_origem}'
        return jsonify({'sucesso': True, 'mensagem': msg})
    except ValueError as e:
        conn.rollback()
        conn.close()
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 400
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro interno: {e}")
        return jsonify({'sucesso': False, 'mensagem': f'Erro interno: {e}'}), 500

# ─── Inicialização ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    criar_tabelas()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
