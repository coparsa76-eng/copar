#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web - Sistema completo com painel do gerente corrigido
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY', 'copar-secret-key-2024')

app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1)
)

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'
)

MAPEAMENTO_LOCAL = {
    'Classificação': 'Classificação',
    'banca': 'Banca',
    'toletagem': 'Toletagem'
}

# ========== FUNÇÕES DE BANCO ==========

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
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER REFERENCES produtores(id),
                tipo_alho VARCHAR(50),
                classe VARCHAR(20),
                peso_kg DECIMAL(10,2),
                local_origem VARCHAR(30),
                data_perda TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                motivo TEXT
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao criar tabela perdas: {e}")

def obter_valor_hora_banca():
    return 16.00

# ========== AUTENTICAÇÃO ==========

def buscar_produtor_por_matricula(matricula):
    if matricula.lower() == 'copar10entrada':
        return {
            'id': 9991,
            'nome': 'Setor Classificação',
            'matricula': 'copar10entrada',
            'especial': True,
            'tipo': 'classificacao'
        }
    if matricula.lower() == 'copar22banca':
        return {
            'id': 9992,
            'nome': 'Setor Banca',
            'matricula': 'copar22banca',
            'especial': True,
            'tipo': 'banca'
        }
    if matricula.lower() == 'copar33toletagem':
        return {
            'id': 9993,
            'nome': 'Setor Toletagem',
            'matricula': 'copar33toletagem',
            'especial': True,
            'tipo': 'toletagem'
        }
    if matricula.upper() == 'GLH':
        return {
            'id': 8888,
            'nome': 'Luis Henrique - Gerente',
            'matricula': 'GLH',
            'especial': True,
            'tipo': 'gerente'
        }
    if matricula.lower() == 'copar10':
        return {
            'id': 9999,
            'nome': 'Super Administrador',
            'matricula': 'copar10',
            'especial': True,
            'tipo': 'superadmin'
        }
    conn = conectar_banco()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s", (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        if produtor:
            return {
                'id': produtor[0],
                'nome': produtor[1],
                'matricula': produtor[2],
                'especial': False,
                'tipo': 'produtor'
            }
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

# ========== FUNÇÕES DE CONSULTA ==========

def buscar_estoque(produtor_id):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tipo_alho, classe, SUM(peso) as total_peso
            FROM estoque 
            WHERE produtor_id = %s AND peso > 0
            GROUP BY tipo_alho, classe
            ORDER BY tipo_alho, classe
        """, (produtor_id,))
        estoque = [{'tipo': row[0], 'classe': row[1], 'peso': float(row[2])} for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return estoque
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
                   v.valor_total, v.valor_produtor, v.status_pagamento, cp.saldo
            FROM vendas v
            JOIN creditos_produtor cp ON v.id = cp.venda_id
            WHERE v.produtor_id = %s
            ORDER BY v.data_venda DESC
        """, (produtor_id,))
        vendas = []
        for row in cursor.fetchall():
            vendas.append({
                'id': row[0],
                'data': row[1].strftime("%d/%m/%Y") if row[1] else "",
                'tipo': row[2],
                'classe': row[3],
                'peso': float(row[4]),
                'valor_total': float(row[5]),
                'valor_produtor': float(row[6]),
                'status': row[7],
                'saldo': float(row[8]) if row[8] else 0
            })
        cursor.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas: {e}")
        return []

def calcular_saldos(vendas):
    total_recebido = sum(v['valor_produtor'] for v in vendas if v['status'] == 'Pago')
    total_a_receber = sum(v['saldo'] for v in vendas if v['status'] != 'Pago')
    return total_recebido, total_a_receber

# ========== FUNÇÃO DE MOVIMENTAÇÃO ==========

def registrar_movimentacao(produtor_id, tipo_alho, classe, peso_movido, local_destino, horas_banca=0, quebra=0, local_origem=None):
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão"
    try:
        cursor = conn.cursor()
        if local_origem:
            local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0)
                FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                AND local_estoque = %s AND peso > 0
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            saldo = float(cursor.fetchone()[0])
            total_retirar = peso_movido + quebra
            if saldo < total_retirar:
                return False, f"Saldo insuficiente em {local_origem_banco}. Disponível: {saldo:.2f} kg"
            cursor.execute("""
                SELECT id, peso FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                AND local_estoque = %s AND peso > 0
                ORDER BY data_registro
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            entradas = cursor.fetchall()
            peso_restante = total_retirar
            for eid, epeso in entradas:
                epeso = float(epeso)
                if peso_restante <= 0:
                    break
                if peso_restante >= epeso:
                    cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
                    peso_restante -= epeso
                else:
                    novo_peso = epeso - peso_restante
                    cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s", (novo_peso, eid))
                    peso_restante = 0
            if quebra > 0:
                cursor.execute("""
                    INSERT INTO perdas (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (produtor_id, tipo_alho, classe, quebra, local_origem_banco, "Quebra na movimentação"))
        if peso_movido - quebra > 0:
            local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)
            cursor.execute("""
                INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (produtor_id, tipo_alho, classe, peso_movido - quebra, local_destino_banco, horas_banca))
            entrada_id = cursor.fetchone()[0]
        else:
            entrada_id = None
        conn.commit()
        cursor.close()
        conn.close()
        return True, entrada_id
    except Exception as e:
        logger.error(f"Erro ao registrar movimentação: {e}")
        if conn:
            conn.rollback()
        return False, str(e)

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
        produtores = [{'matricula': r[0], 'nome': r[1], 'id': r[2]} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return produtores
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

# ========== FUNÇÕES PARA O GERENTE (CORRIGIDAS) ==========

def obter_estatisticas_gerais():
    """Retorna estatísticas para o dashboard do gerente"""
    conn = conectar_banco()
    if not conn:
        return {
            'total_produtores': 0,
            'total_estoque_kg': 0,
            'estoque_classificacao': 0,
            'estoque_banca': 0,
            'estoque_toletagem': 0,
            'vendas_mes': 0,
            'pagamentos_mes': 0,
            'saldo_total': 0,
            'perdas_mes': 0
        }
    try:
        cursor = conn.cursor()
        
        # Total de produtores
        cursor.execute("SELECT COUNT(*) FROM produtores")
        total_produtores = cursor.fetchone()[0]
        
        # Total em estoque (Kg)
        cursor.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE peso > 0")
        total_estoque_kg = float(cursor.fetchone()[0])
        
        # Estoque por local
        cursor.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE local_estoque = 'Classificação' AND peso > 0")
        estoque_classificacao = float(cursor.fetchone()[0])
        
        cursor.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE local_estoque = 'Banca' AND peso > 0")
        estoque_banca = float(cursor.fetchone()[0])
        
        cursor.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE local_estoque = 'Toletagem' AND peso > 0")
        estoque_toletagem = float(cursor.fetchone()[0])
        
        # Vendas do MÊS ATUAL
        cursor.execute("""
            SELECT COALESCE(SUM(valor_total), 0) 
            FROM vendas 
            WHERE EXTRACT(YEAR FROM data_venda) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM data_venda) = EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        vendas_mes = float(cursor.fetchone()[0])
        
        # Pagamentos do MÊS ATUAL
        cursor.execute("""
            SELECT COALESCE(SUM(valor_total), 0) 
            FROM pagamentos 
            WHERE EXTRACT(YEAR FROM data_pagamento) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM data_pagamento) = EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        pagamentos_mes = float(cursor.fetchone()[0])
        
        # Saldo total a pagar
        cursor.execute("SELECT COALESCE(SUM(saldo), 0) FROM creditos_produtor")
        saldo_total = float(cursor.fetchone()[0])
        
        # Perdas do mês
        cursor.execute("""
            SELECT COALESCE(SUM(peso_kg), 0) 
            FROM perdas 
            WHERE EXTRACT(YEAR FROM data_perda) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM data_perda) = EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        perdas_mes = float(cursor.fetchone()[0])
        
        cursor.close()
        conn.close()
        
        return {
            'total_produtores': total_produtores,
            'total_estoque_kg': total_estoque_kg,
            'estoque_classificacao': estoque_classificacao,
            'estoque_banca': estoque_banca,
            'estoque_toletagem': estoque_toletagem,
            'vendas_mes': vendas_mes,
            'pagamentos_mes': pagamentos_mes,
            'saldo_total': saldo_total,
            'perdas_mes': perdas_mes
        }
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        return {
            'total_produtores': 0,
            'total_estoque_kg': 0,
            'estoque_classificacao': 0,
            'estoque_banca': 0,
            'estoque_toletagem': 0,
            'vendas_mes': 0,
            'pagamentos_mes': 0,
            'saldo_total': 0,
            'perdas_mes': 0
        }

def obter_estoque_hierarquico():
    """Retorna estoque hierárquico: Local -> Tipo -> Classe -> Produtor"""
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                e.local_estoque,
                e.tipo_alho,
                e.classe,
                p.nome as produtor,
                SUM(e.peso) as total_peso,
                SUM(e.horas_banca) as total_horas
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.peso > 0
            GROUP BY e.local_estoque, e.tipo_alho, e.classe, p.nome
            ORDER BY e.local_estoque, e.tipo_alho, e.classe, p.nome
        """)
        
        # Organizar em estrutura hierárquica
        hierarquia = {}
        for row in cursor.fetchall():
            local = row[0]
            tipo = row[1]
            classe = row[2]
            produtor = row[3]
            peso = float(row[4])
            horas = float(row[5])
            
            if local not in hierarquia:
                hierarquia[local] = {}
            if tipo not in hierarquia[local]:
                hierarquia[local][tipo] = {}
            if classe not in hierarquia[local][tipo]:
                hierarquia[local][tipo][classe] = []
            
            hierarquia[local][tipo][classe].append({
                'produtor': produtor,
                'peso': peso,
                'horas': horas
            })
        
        cursor.close()
        conn.close()
        
        # Converter para formato serializável
        resultado = []
        for local, tipos in hierarquia.items():
            local_item = {'local': local, 'tipos': []}
            for tipo, classes in tipos.items():
                tipo_item = {'tipo': tipo, 'classes': []}
                for classe, produtores in classes.items():
                    total_peso = sum(p['peso'] for p in produtores)
                    total_horas = sum(p['horas'] for p in produtores)
                    classe_item = {
                        'classe': classe,
                        'total_peso': total_peso,
                        'total_horas': total_horas,
                        'produtores': produtores
                    }
                    tipo_item['classes'].append(classe_item)
                local_item['tipos'].append(tipo_item)
            resultado.append(local_item)
        
        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar estoque hierárquico: {e}")
        return []

def obter_vendas_recentes(limite=50):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, p.nome as produtor, v.tipo_alho, v.classe, v.peso,
                   v.valor_total, v.valor_produtor, v.status_pagamento, v.data_venda
            FROM vendas v
            JOIN produtores p ON v.produtor_id = p.id
            WHERE EXTRACT(YEAR FROM v.data_venda) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM v.data_venda) = EXTRACT(MONTH FROM CURRENT_DATE)
            ORDER BY v.data_venda DESC
            LIMIT %s
        """, (limite,))
        vendas = []
        for r in cursor.fetchall():
            vendas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'valor_total': float(r[5]), 'valor_produtor': float(r[6]),
                'status': r[7], 'data': r[8].strftime("%d/%m/%Y") if r[8] else ""
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
            SELECT pa.id, p.nome as produtor, pa.valor_total, pa.forma_pagamento, pa.data_pagamento
            FROM pagamentos pa
            JOIN produtores p ON pa.produtor_id = p.id
            WHERE EXTRACT(YEAR FROM pa.data_pagamento) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM pa.data_pagamento) = EXTRACT(MONTH FROM CURRENT_DATE)
            ORDER BY pa.data_pagamento DESC
            LIMIT %s
        """, (limite,))
        pagamentos = []
        for r in cursor.fetchall():
            pagamentos.append({
                'id': r[0], 'produtor': r[1], 'valor': float(r[2]), 'forma': r[3],
                'data': r[4].strftime("%d/%m/%Y") if r[4] else ""
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
            SELECT tipo_alho, COALESCE(SUM(peso), 0) as total_peso
            FROM estoque
            WHERE peso > 0
            GROUP BY tipo_alho
            ORDER BY total_peso DESC
        """)
        estoque = [{'tipo': r[0], 'peso': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return estoque
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
            SELECT TO_CHAR(DATE_TRUNC('month', data_venda), 'Mon/YYYY') as mes,
                   COALESCE(SUM(valor_total), 0) as total_vendas
            FROM vendas
            WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', data_venda)
            ORDER BY DATE_TRUNC('month', data_venda)
        """)
        vendas = [{'mes': r[0], 'total': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return vendas
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
            SELECT p.id, pr.nome as produtor, p.tipo_alho, p.classe, p.peso_kg, 
                   p.local_origem, p.data_perda, p.motivo
            FROM perdas p
            JOIN produtores pr ON p.produtor_id = pr.id
            WHERE EXTRACT(YEAR FROM p.data_perda) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND EXTRACT(MONTH FROM p.data_perda) = EXTRACT(MONTH FROM CURRENT_DATE)
            ORDER BY p.data_perda DESC
            LIMIT %s
        """, (limite,))
        perdas = []
        for r in cursor.fetchall():
            perdas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'local_origem': r[5],
                'data': r[6].strftime("%d/%m/%Y") if r[6] else "",
                'motivo': r[7] or ''
            })
        cursor.close()
        conn.close()
        return perdas
    except Exception as e:
        logger.error(f"Erro ao buscar perdas recentes: {e}")
        return []

# ========== ROTAS ==========

@app.route('/')
def index():
    if 'produtor_id' in session:
        tipo = session.get('tipo')
        if tipo == 'gerente':
            return redirect(url_for('gerente'))
        elif tipo in ['classificacao', 'banca', 'toletagem', 'superadmin']:
            return redirect(url_for('registro_entrada'))
        else:
            return redirect(url_for('produtor'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        if not matricula:
            return render_template('login.html', erro='Digite sua matrícula')
        produtor = buscar_produtor_por_matricula(matricula)
        if produtor:
            session['produtor_id'] = produtor['id']
            session['produtor_nome'] = produtor['nome']
            session['produtor_matricula'] = produtor['matricula']
            session['acesso_especial'] = produtor.get('especial', False)
            session['tipo'] = produtor.get('tipo', 'produtor')
            if session['tipo'] == 'gerente':
                return redirect(url_for('gerente'))
            elif session['tipo'] in ['classificacao', 'banca', 'toletagem', 'superadmin']:
                return redirect(url_for('registro_entrada'))
            else:
                return redirect(url_for('produtor'))
        else:
            return render_template('login.html', erro='Matrícula não encontrada')
    return render_template('login.html', erro=None)

@app.route('/produtor')
def produtor():
    if 'produtor_id' not in session or session.get('tipo') not in [None, 'produtor']:
        return redirect(url_for('login'))
    produtor_id = session['produtor_id']
    produtor_nome = session['produtor_nome']
    estoque = buscar_estoque(produtor_id)
    vendas = buscar_vendas(produtor_id)
    total_recebido, total_a_receber = calcular_saldos(vendas)
    return render_template('produtor.html',
                         nome=produtor_nome,
                         estoque=estoque,
                         vendas=vendas,
                         total_recebido=total_recebido,
                         total_a_receber=total_a_receber)

@app.route('/registro-entrada')
def registro_entrada():
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    tipo = session.get('tipo')
    if tipo not in ['classificacao', 'banca', 'toletagem', 'superadmin']:
        return redirect(url_for('produtor'))
    return render_template('registro_entrada.html',
                         role=tipo,
                         valor_hora_banca=16.00)

@app.route('/gerente')
def gerente():
    if 'produtor_id' not in session or session.get('tipo') != 'gerente':
        return redirect(url_for('login'))
    return render_template('gerente.html')

# ========== APIS ==========

@app.route('/api/buscar-produtor', methods=['POST'])
def api_buscar_produtor():
    data = request.get_json()
    matricula = data.get('matricula', '').strip()
    if not matricula:
        return jsonify({'encontrado': False, 'mensagem': 'Matrícula não informada'})
    conn = conectar_banco()
    if not conn:
        return jsonify({'encontrado': False, 'mensagem': 'Erro de conexão'})
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s", (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        if produtor:
            return jsonify({'encontrado': True, 'id': produtor[0], 'matricula': produtor[2], 'nome': produtor[1]})
        else:
            return jsonify({'encontrado': False, 'mensagem': 'Produtor não encontrado'})
    except Exception as e:
        logger.error(f"Erro na API de busca: {e}")
        return jsonify({'encontrado': False, 'mensagem': str(e)})

@app.route('/api/buscar-produtores', methods=['GET'])
def api_buscar_produtores():
    termo = request.args.get('termo', '').strip()
    if len(termo) < 1:
        return jsonify([])
    produtores = buscar_produtores_por_termo(termo)
    return jsonify(produtores)

@app.route('/api/obter-saldo', methods=['POST'])
def api_obter_saldo():
    data = request.get_json()
    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    classe = data.get('classe')
    local = data.get('local')
    if not all([produtor_id, tipo_alho, classe, local]):
        return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos'})
    saldo = obter_saldo_estoque(produtor_id, tipo_alho, classe, local)
    return jsonify({'sucesso': True, 'saldo': saldo})

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    data = request.get_json()
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400
    role = session.get('tipo')
    if role not in ['classificacao', 'banca', 'toletagem', 'superadmin']:
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado'}), 403
    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem = data.get('local_origem')
    detalhes = data.get('detalhes', [])
    horas_banca = data.get('horas_banca', 0)
    quebra = data.get('quebra', 0)
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})
    if role == 'classificacao':
        if local_destino != 'Classificação':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Classificação só pode registrar entrada inicial (Classificação).'})
        local_origem = None
        if horas_banca > 0 or quebra > 0:
            return jsonify({'sucesso': False, 'mensagem': 'Classificação não permite horas ou quebra.'})
    elif role == 'banca':
        if local_destino != 'banca':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Banca só pode transferir para Banca.'})
        if not local_origem:
            return jsonify({'sucesso': False, 'mensagem': 'Selecione a origem do estoque.'})
        if local_origem not in ['Classificação', 'Toletagem']:
            return jsonify({'sucesso': False, 'mensagem': 'Para Banca, a origem deve ser Classificação ou Toletagem.'})
    elif role == 'toletagem':
        if local_destino != 'toletagem':
            return jsonify({'sucesso': False, 'mensagem': 'Setor Toletagem só pode transferir para Toletagem.'})
        if not local_origem:
            return jsonify({'sucesso': False, 'mensagem': 'Selecione a origem do estoque.'})
        if local_origem not in ['Classificação', 'Banca']:
            return jsonify({'sucesso': False, 'mensagem': 'Para Toletagem, a origem deve ser Classificação ou Banca.'})
    classes_mapeamento = {
        "INDÚSTRIA": "Indústria",
        "TIPO 2": "Classe 2",
        "TIPO 3": "Classe 3",
        "TIPO 4": "Classe 4",
        "TIPO 5": "Classe 5",
        "TIPO 6": "Classe 6",
        "TIPO 7": "Classe 7"
    }
    resultados = []
    erros = []
    peso_total_movido = 0
    for item in detalhes:
        classe_origem = item.get('classe')
        peso = item.get('peso', 0)
        if peso <= 0:
            continue
        classe_destino = classes_mapeamento.get(classe_origem)
        if not classe_destino:
            erros.append({'classe': classe_origem, 'peso': peso, 'erro': f'Classe {classe_origem} não reconhecida'})
            continue
        peso_total_movido += peso
        if quebra > 0 and peso_total_movido > 0:
            quebra_proporcional = peso * quebra / peso_total_movido
        else:
            quebra_proporcional = 0
        sucesso, resultado = registrar_movimentacao(
            produtor_id, tipo_alho, classe_destino, peso,
            local_destino, horas_banca=horas_banca, quebra=quebra_proporcional, local_origem=local_origem
        )
        if sucesso:
            resultados.append({'classe': classe_origem, 'peso': peso, 'entrada_id': resultado})
        else:
            erros.append({'classe': classe_origem, 'peso': peso, 'erro': resultado})
    if erros:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro ao salvar alguns itens: {erros[0]["erro"]}',
            'sucessos': resultados,
            'erros': erros
        }), 207
    msg = f'Registro realizado com sucesso! Total movido: {peso_total_movido - quebra:.2f} Kg'
    if quebra > 0:
        msg += f' (Quebra: {quebra:.2f} Kg)'
    if horas_banca > 0:
        msg += f' | Horas de banca: {horas_banca}'
    if local_origem:
        msg += f' | Origem: {local_origem}'
    return jsonify({'sucesso': True, 'mensagem': msg, 'registros': resultados})

# APIs para o gerente
@app.route('/api/gerente/estatisticas')
def api_gerente_estatisticas():
    return jsonify(obter_estatisticas_gerais())

@app.route('/api/gerente/estoque-hierarquico')
def api_gerente_estoque_hierarquico():
    return jsonify(obter_estoque_hierarquico())

@app.route('/api/gerente/vendas-recentes')
def api_gerente_vendas_recentes():
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_vendas_recentes(limite))

@app.route('/api/gerente/pagamentos-recentes')
def api_gerente_pagamentos_recentes():
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_pagamentos_recentes(limite))

@app.route('/api/gerente/estoque-por-tipo')
def api_gerente_estoque_por_tipo():
    return jsonify(obter_estoque_por_tipo())

@app.route('/api/gerente/vendas-por-mes')
def api_gerente_vendas_por_mes():
    return jsonify(obter_vendas_por_mes())

@app.route('/api/gerente/perdas-recentes')
def api_gerente_perdas_recentes():
    limite = request.args.get('limite', 50, type=int)
    return jsonify(obter_perdas_recentes(limite))

@app.route('/api/salvar-configuracoes', methods=['POST'])
def api_salvar_configuracoes():
    return jsonify({'sucesso': True, 'mensagem': 'Configuração salva'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    criar_tabela_perdas()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
