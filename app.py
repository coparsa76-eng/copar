#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web — app.py definitivo com todas as tabelas
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg
import os
import logging
import traceback
from datetime import timedelta

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

# ── Mapeamentos ──────────────────────────────────────────────────────────────

MAPEAMENTO_LOCAL = {
    'Classificação': 'Classificação',
    'classificacao': 'Classificação',
    'banca':         'Banca',
    'Banca':         'Banca',
    'toletagem':     'Toletagem',
    'Toletagem':     'Toletagem',
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
    'copar10entrada':   {'id': 9991, 'nome': 'Setor Classificação',     'tipo': 'classificacao'},
    'copar22banca':     {'id': 9992, 'nome': 'Setor Banca',             'tipo': 'banca'},
    'copar33toletagem': {'id': 9993, 'nome': 'Setor Toletagem',         'tipo': 'toletagem'},
    'glh':              {'id': 8888, 'nome': 'Luis Henrique – Gerente', 'tipo': 'gerente'},
    'copar10':          {'id': 9999, 'nome': 'Super Administrador',     'tipo': 'superadmin'},
}

# ── Banco ────────────────────────────────────────────────────────────────────

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return None

def criar_tabelas():
    """Cria todas as tabelas necessárias se não existirem."""
    conn = conectar_banco()
    if not conn:
        logger.error("Não foi possível conectar para criar tabelas")
        return False
    
    try:
        cur = conn.cursor()
        
        # Tabela produtores
        cur.execute("""
            CREATE TABLE IF NOT EXISTS produtores (
                id SERIAL PRIMARY KEY,
                matricula VARCHAR(20) UNIQUE NOT NULL,
                nome VARCHAR(100) NOT NULL
            )
        """)
        
        # Tabela estoque
        cur.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id),
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
                produtor_id INTEGER REFERENCES produtores(id),
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
                produtor_id INTEGER REFERENCES produtores(id),
                valor_total DECIMAL(10,2),
                forma_pagamento VARCHAR(50),
                data_pagamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela creditos_produtor
        cur.execute("""
            CREATE TABLE IF NOT EXISTS creditos_produtor (
                id SERIAL PRIMARY KEY,
                venda_id INTEGER REFERENCES vendas(id),
                saldo DECIMAL(10,2) DEFAULT 0
            )
        """)
        
        # Tabela perdas
        cur.execute("""
            CREATE TABLE IF NOT EXISTS perdas (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id),
                tipo_alho VARCHAR(50),
                classe VARCHAR(20),
                peso_kg DECIMAL(10,4),
                local_origem VARCHAR(30),
                data_perda TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                motivo TEXT
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Todas as tabelas criadas/verificadas com sucesso")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao criar tabelas: {e}")
        logger.error(traceback.format_exc())
        conn.close()
        return False

# ── Autenticação ─────────────────────────────────────────────────────────────

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

# ── Consultas produtor ───────────────────────────────────────────────────────

def buscar_estoque(produtor_id):
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tipo_alho, classe, SUM(peso) FROM estoque
            WHERE produtor_id = %s AND peso > 0
            GROUP BY tipo_alho, classe ORDER BY tipo_alho, classe
        """, (produtor_id,))
        result = [{'tipo': r[0], 'classe': r[1], 'peso': float(r[2])} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar estoque: {e}")
        return []

def buscar_vendas(produtor_id):
    conn = conectar_banco()
    if not conn: return []
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
            vendas.append({'id': r[0],
                           'data': r[1].strftime("%d/%m/%Y") if r[1] else "",
                           'tipo': r[2], 'classe': r[3],
                           'peso': float(r[4]), 'valor_total': float(r[5]),
                           'valor_produtor': float(r[6]), 'status': r[7],
                           'saldo': float(r[8])})
        cur.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas: {e}")
        return []

def calcular_saldos(vendas):
    return (
        sum(v['valor_produtor'] for v in vendas if v['status'] == 'Pago'),
        sum(v['saldo'] for v in vendas if v['status'] != 'Pago'),
    )

def buscar_produtores_por_termo(termo):
    conn = conectar_banco()
    if not conn: return []
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

# ── Núcleo de movimentação ───────────────────────────────────────────────────

def _retirar_fifo(cur, produtor_id, tipo_alho, classe_banco, local_banco, quantidade):
    """Retira quantidade usando FIFO"""
    logger.debug(f"Retirando {quantidade}kg de {classe_banco} em {local_banco}")
    
    cur.execute("""
        SELECT id, peso FROM estoque
        WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
          AND local_estoque = %s AND peso > 0
        ORDER BY data_registro, id
        FOR UPDATE
    """, (produtor_id, tipo_alho, classe_banco, local_banco))
    rows = cur.fetchall()
    
    saldo = sum(float(r[1]) for r in rows)
    if saldo < quantidade - 0.001:
        raise ValueError(
            f"Saldo insuficiente em {local_banco} para {classe_banco}. "
            f"Disponível: {saldo:.3f} kg, necessário: {quantidade:.3f} kg"
        )
    
    restante = quantidade
    for eid, epeso in rows:
        if restante <= 0.001:
            break
        epeso = float(epeso)
        if restante >= epeso - 0.001:
            cur.execute("DELETE FROM estoque WHERE id = %s", (eid,))
            restante -= epeso
            logger.debug(f"  Removido registro {eid} completamente ({epeso}kg)")
        else:
            novo_peso = round(epeso - restante, 4)
            cur.execute("UPDATE estoque SET peso = %s WHERE id = %s", (novo_peso, eid))
            logger.debug(f"  Atualizado registro {eid}: {epeso}kg -> {novo_peso}kg")
            restante = 0

def _inserir_estoque(cur, produtor_id, tipo_alho, classe_banco, peso, local_banco, horas=0):
    """Insere uma linha de estoque"""
    logger.debug(f"Inserindo {peso}kg em {local_banco} para {classe_banco}")
    cur.execute("""
        INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (produtor_id, tipo_alho, classe_banco, round(peso, 4), local_banco, horas))
    new_id = cur.fetchone()[0]
    logger.debug(f"  Inserido com ID {new_id}")
    return new_id

def _registrar_perda(cur, produtor_id, tipo_alho, classe_banco, peso, local_banco, motivo):
    """Registra uma perda"""
    logger.debug(f"Registrando perda de {peso}kg de {classe_banco} em {local_banco}")
    cur.execute("""
        INSERT INTO perdas (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (produtor_id, tipo_alho, classe_banco, round(peso, 4), local_banco, motivo))

# ── Consultas gerente ────────────────────────────────────────────────────────

def obter_estatisticas_gerais():
    stats = dict(total_produtores=0, total_estoque_kg=0,
                 estoque_classificacao=0, estoque_banca=0, estoque_toletagem=0,
                 vendas_mes=0, pagamentos_mes=0, perdas_mes=0)
    conn = conectar_banco()
    if not conn:
        return stats
    try:
        queries = {
            'total_produtores': ("SELECT COUNT(*) FROM produtores", False),
            'total_estoque_kg': ("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE peso>0", True),
            'estoque_classificacao': ("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Classificação' AND peso>0", True),
            'estoque_banca': ("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Banca' AND peso>0", True),
            'estoque_toletagem': ("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Toletagem' AND peso>0", True),
            'vendas_mes': ("SELECT COALESCE(SUM(valor_total),0) FROM vendas WHERE DATE_TRUNC('month',data_venda)=DATE_TRUNC('month',CURRENT_DATE)", True),
            'pagamentos_mes': ("SELECT COALESCE(SUM(valor_total),0) FROM pagamentos WHERE DATE_TRUNC('month',data_pagamento)=DATE_TRUNC('month',CURRENT_DATE)", True),
            'perdas_mes': ("SELECT COALESCE(SUM(peso_kg),0) FROM perdas WHERE DATE_TRUNC('month',data_perda)=DATE_TRUNC('month',CURRENT_DATE)", True),
        }
        for key, (sql, is_float) in queries.items():
            try:
                cur = conn.cursor()
                cur.execute(sql)
                val = cur.fetchone()[0]
                stats[key] = float(val) if is_float else int(val)
                cur.close()
            except Exception as e:
                logger.error(f"Erro stat {key}: {e}")
        conn.close()
    except Exception as e:
        logger.error(f"Erro estatísticas: {e}")
    return stats

def obter_estoque_hierarquico():
    conn = conectar_banco()
    if not conn: return []
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
            hier.setdefault(local, {}).setdefault(tipo, {}).setdefault(classe, [])
            hier[local][tipo][classe].append({'produtor': prod, 'peso': peso, 'horas': horas})
        cur.close()
        conn.close()
        result = []
        for local, tipos in hier.items():
            li = {'local': local, 'tipos': []}
            for tipo, classes in tipos.items():
                ti = {'tipo': tipo, 'classes': []}
                for classe, prods in classes.items():
                    ti['classes'].append({
                        'classe': classe,
                        'total_peso': sum(p['peso'] for p in prods),
                        'total_horas': sum(p['horas'] for p in prods),
                        'produtores': prods,
                    })
                li['tipos'].append(ti)
            result.append(li)
        return result
    except Exception as e:
        logger.error(f"Erro estoque hierárquico: {e}")
        return []

def obter_vendas_recentes(limite=50):
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, p.nome, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento, v.data_venda
            FROM vendas v JOIN produtores p ON v.produtor_id = p.id
            WHERE DATE_TRUNC('month',v.data_venda)=DATE_TRUNC('month',CURRENT_DATE)
            ORDER BY v.data_venda DESC LIMIT %s
        """, (limite,))
        rows = [{'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                 'peso': float(r[4]), 'valor_total': float(r[5]), 'valor_produtor': float(r[6]),
                 'status': r[7], 'data': r[8].strftime("%d/%m/%Y") if r[8] else ""}
                for r in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Erro vendas: {e}")
        return []

def obter_pagamentos_recentes(limite=50):
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pa.id, p.nome, pa.valor_total, pa.forma_pagamento, pa.data_pagamento
            FROM pagamentos pa JOIN produtores p ON pa.produtor_id = p.id
            WHERE DATE_TRUNC('month',pa.data_pagamento)=DATE_TRUNC('month',CURRENT_DATE)
            ORDER BY pa.data_pagamento DESC LIMIT %s
        """, (limite,))
        rows = [{'id': r[0], 'produtor': r[1], 'valor': float(r[2]),
                 'forma': r[3], 'data': r[4].strftime("%d/%m/%Y") if r[4] else ""}
                for r in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Erro pagamentos: {e}")
        return []

def obter_estoque_por_tipo():
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT tipo_alho, COALESCE(SUM(peso),0) FROM estoque WHERE peso>0 GROUP BY tipo_alho ORDER BY 2 DESC")
        r = [{'tipo': row[0], 'peso': float(row[1])} for row in cur.fetchall()]
        cur.close()
        conn.close()
        return r
    except Exception as e:
        logger.error(f"Erro estoque tipo: {e}")
        return []

def obter_vendas_por_mes():
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month',data_venda),'Mon/YYYY'),
                   COALESCE(SUM(valor_total),0)
            FROM vendas WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month',data_venda)
            ORDER BY DATE_TRUNC('month',data_venda)
        """)
        r = [{'mes': row[0], 'total': float(row[1])} for row in cur.fetchall()]
        cur.close()
        conn.close()
        return r
    except Exception as e:
        logger.error(f"Erro vendas mês: {e}")
        return []

def obter_perdas_recentes(limite=50):
    conn = conectar_banco()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, pr.nome, p.tipo_alho, p.classe, p.peso_kg,
                   p.local_origem, p.data_perda, p.motivo
            FROM perdas p JOIN produtores pr ON p.produtor_id = pr.id
            WHERE DATE_TRUNC('month',p.data_perda)=DATE_TRUNC('month',CURRENT_DATE)
            ORDER BY p.data_perda DESC LIMIT %s
        """, (limite,))
        rows = [{'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                 'peso': float(r[4]), 'local_origem': r[5],
                 'data': r[6].strftime("%d/%m/%Y") if r[6] else "", 'motivo': r[7] or ''}
                for r in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Erro perdas: {e}")
        return []

# ── Rotas ────────────────────────────────────────────────────────────────────

def _redirecionar(tipo):
    if tipo == 'gerente':
        return redirect(url_for('gerente'))
    if tipo in ('classificacao','banca','toletagem','superadmin'):
        return redirect(url_for('registro_entrada'))
    return redirect(url_for('produtor'))

@app.route('/')
def index():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    return _redirecionar(session.get('tipo'))

@app.route('/login', methods=['GET','POST'])
def login():
    if 'produtor_id' in session:
        return _redirecionar(session.get('tipo'))
    if request.method == 'POST':
        mat = request.form.get('matricula','').strip()
        if not mat:
            return render_template('login.html', erro='Digite sua matrícula')
        prod = buscar_produtor_por_matricula(mat)
        if prod:
            session.permanent = True
            session.update({'produtor_id': prod['id'], 'produtor_nome': prod['nome'],
                            'produtor_matricula': prod['matricula'],
                            'acesso_especial': prod.get('especial', False),
                            'tipo': prod.get('tipo','produtor')})
            return _redirecionar(session['tipo'])
        return render_template('login.html', erro='Matrícula não encontrada')
    return render_template('login.html', erro=None)

@app.route('/produtor')
def produtor():
    if 'produtor_id' not in session or session.get('tipo') not in (None,'produtor'):
        return redirect(url_for('login'))
    pid = session['produtor_id']
    estoque = buscar_estoque(pid)
    vendas = buscar_vendas(pid)
    tr, ta = calcular_saldos(vendas)
    return render_template('produtor.html', nome=session['produtor_nome'],
                           estoque=estoque, vendas=vendas,
                           total_recebido=tr, total_a_receber=ta)

@app.route('/registro-entrada')
def registro_entrada():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    tipo = session.get('tipo')
    if tipo not in ('classificacao','banca','toletagem','superadmin'):
        return redirect(url_for('produtor'))
    return render_template('registro_entrada.html', role=tipo,
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

# ── APIs ─────────────────────────────────────────────────────────────────────

@app.route('/api/buscar-produtores')
def api_buscar_produtores():
    termo = request.args.get('termo','').strip()
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
            FROM estoque
            WHERE produtor_id=%s AND tipo_alho=%s AND local_estoque=%s AND peso>0
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
    logger.info("=" * 50)
    logger.info("INICIANDO SALVAR-ENTRADA")
    
    data = request.get_json(silent=True)
    if not data:
        logger.error("Dados inválidos - JSON vazio")
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400

    role = session.get('tipo')
    logger.info(f"Role do usuário: {role}")
    
    if role not in ('classificacao','banca','toletagem','superadmin'):
        logger.error(f"Acesso não autorizado - role: {role}")
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado'}), 403

    pid = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem = data.get('local_origem')
    detalhes = data.get('detalhes', [])
    horas_banca = float(data.get('horas_banca', 0) or 0)

    logger.info(f"Dados recebidos: produtor_id={pid}, tipo_alho={tipo_alho}")
    logger.info(f"local_destino={local_destino}, local_origem={local_origem}")
    logger.info(f"horas_banca={horas_banca}")
    logger.info(f"Detalhes: {detalhes}")

    if not pid or not tipo_alho or not detalhes:
        logger.error("Dados incompletos")
        return jsonify({'sucesso': False, 'mensagem': 'Dados incompletos'}), 400

    # Mapeia os locais para os nomes usados no banco
    local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)
    local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem) if local_origem else None
    
    logger.info(f"Locais mapeados: destino={local_destino_banco}, origem={local_origem_banco}")

    # Validações de acordo com o papel
    if role == 'classificacao':
        if local_destino_banco != 'Classificação':
            return jsonify({'sucesso': False, 'mensagem': 'Classificação só registra entrada inicial.'})
        local_origem_banco = None
        
    elif role == 'banca':
        if local_destino_banco != 'Banca':
            logger.error(f"Destino inválido para banca: {local_destino_banco}")
            return jsonify({'sucesso': False, 'mensagem': 'Banca só transfere para Banca.'})
        if not local_origem_banco or local_origem_banco not in ('Classificação','Toletagem'):
            logger.error(f"Origem inválida para banca: {local_origem_banco}")
            return jsonify({'sucesso': False, 'mensagem': 'Origem deve ser Classificação ou Toletagem.'})
            
    elif role == 'toletagem':
        if local_destino_banco != 'Toletagem':
            logger.error(f"Destino inválido para toletagem: {local_destino_banco}")
            return jsonify({'sucesso': False, 'mensagem': 'Toletagem só transfere para Toletagem.'})
        if not local_origem_banco or local_origem_banco not in ('Classificação','Banca'):
            logger.error(f"Origem inválida para toletagem: {local_origem_banco}")
            return jsonify({'sucesso': False, 'mensagem': 'Origem deve ser Classificação ou Banca.'})

    conn = conectar_banco()
    if not conn:
        logger.error("Falha na conexão com banco")
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão'}), 500

    conn.autocommit = False
    
    try:
        cur = conn.cursor()
        total_destino = 0
        total_perdas = 0

        for idx, item in enumerate(detalhes):
            classe_ui = item.get('classe', '')
            peso = float(item.get('peso', 0) or 0)
            tipo_item = item.get('tipo', '')

            logger.info(f"Processando item {idx+1}: classe={classe_ui}, peso={peso}, tipo={tipo_item}")

            if peso <= 0.001:
                logger.warning(f"  Peso ignorado (muito pequeno): {peso}")
                continue

            classe_banco = CLASSES_MAP.get(classe_ui)
            if not classe_banco:
                raise ValueError(f'Classe "{classe_ui}" não reconhecida')
            
            logger.info(f"  Classe mapeada: {classe_ui} -> {classe_banco}")

            if tipo_item == 'entrada':
                _inserir_estoque(cur, pid, tipo_alho, classe_banco,
                                 peso, local_destino_banco, horas_banca)
                total_destino += peso
                logger.info(f"  ✓ Entrada direta registrada")

            elif tipo_item == 'transferencia':
                if not local_origem_banco:
                    raise ValueError(f'Origem não informada para transferência de {classe_ui}')
                _retirar_fifo(cur, pid, tipo_alho, classe_banco,
                              local_origem_banco, peso)
                _inserir_estoque(cur, pid, tipo_alho, classe_banco,
                                 peso, local_destino_banco, horas_banca)
                total_destino += peso
                logger.info(f"  ✓ Transferência registrada")

            elif tipo_item == 'perda':
                if not local_origem_banco:
                    raise ValueError(f'Origem não informada para perda de {classe_ui}')
                _retirar_fifo(cur, pid, tipo_alho, classe_banco,
                              local_origem_banco, peso)
                _registrar_perda(cur, pid, tipo_alho, classe_banco,
                                 peso, local_origem_banco, 'Perda/impureza na movimentação')
                total_perdas += peso
                logger.info(f"  ✓ Perda registrada")

            elif tipo_item == 'industria':
                _inserir_estoque(cur, pid, tipo_alho, classe_banco,
                                 peso, local_destino_banco, horas_banca)
                total_destino += peso
                logger.info(f"  ✓ Indústria registrada")

            else:
                logger.warning(f"  Tipo de item desconhecido: {tipo_item}")

        conn.commit()
        logger.info(f"Transação commitada com sucesso!")
        logger.info(f"Resumo: Destino={total_destino:.2f}kg, Perdas={total_perdas:.2f}kg")
        
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
        logger.error(f"Erro de validação: {e}")
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 400
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro interno: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'sucesso': False, 'mensagem': f'Erro interno: {str(e)}'}), 500

# ── APIs Gerente ─────────────────────────────────────────────────────────────

def _check_gerente():
    return 'produtor_id' not in session or session.get('tipo') != 'gerente'

@app.route('/api/gerente/estatisticas')
def api_gerente_estatisticas():
    if _check_gerente():
        return jsonify({}), 403
    return jsonify(obter_estatisticas_gerais())

@app.route('/api/gerente/estoque-hierarquico')
def api_gerente_estoque_hierarquico():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_estoque_hierarquico())

@app.route('/api/gerente/vendas-recentes')
def api_gerente_vendas_recentes():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_vendas_recentes(request.args.get('limite',50,type=int)))

@app.route('/api/gerente/pagamentos-recentes')
def api_gerente_pagamentos_recentes():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_pagamentos_recentes(request.args.get('limite',50,type=int)))

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

@app.route('/api/gerente/perdas-recentes')
def api_gerente_perdas_recentes():
    if _check_gerente():
        return jsonify([]), 403
    return jsonify(obter_perdas_recentes(request.args.get('limite',50,type=int)))

# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Cria todas as tabelas antes de iniciar
    if criar_tabelas():
        logger.info("Tabelas criadas/verificadas com sucesso")
    else:
        logger.error("Falha ao criar tabelas. O sistema pode não funcionar corretamente.")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)  # debug=True para ver logs
