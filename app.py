#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web — app.py final corrigido
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

# Mapeamentos
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

# Usuários especiais
USUARIOS_ESPECIAIS = {
    'copar10entrada':   {'id': 9991, 'nome': 'Setor Classificação',     'tipo': 'classificacao'},
    'copar22banca':     {'id': 9992, 'nome': 'Setor Banca',             'tipo': 'banca'},
    'copar33toletagem': {'id': 9993, 'nome': 'Setor Toletagem',         'tipo': 'toletagem'},
    'glh':              {'id': 8888, 'nome': 'Luis Henrique – Gerente', 'tipo': 'gerente'},
    'copar10':          {'id': 9999, 'nome': 'Super Administrador',     'tipo': 'superadmin'},
}

# ─────────────────────────────────────────────────────────────────────────────
#  Conexão e tabelas
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
#  Autenticação e consultas básicas
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
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s", (matricula.strip(),))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return {'id': row[0], 'nome': row[1], 'matricula': row[2], 'especial': False, 'tipo': 'produtor'}
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

def buscar_produtores_por_termo(termo):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT matricula, nome, id FROM produtores
            WHERE matricula ILIKE %s OR nome ILIKE %s ORDER BY nome LIMIT 20
        """, (f'%{termo}%', f'%{termo}%'))
        result = [{'matricula': r[0], 'nome': r[1], 'id': r[2]} for r in cursor.fetchall()]
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
            SELECT COALESCE(SUM(peso), 0) FROM estoque
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
#  Funções de movimentação
# ─────────────────────────────────────────────────────────────────────────────

def registrar_movimentacao(cursor, produtor_id, tipo_alho, classe_banco,
                            peso, local_destino, horas_banca=0,
                            local_origem=None):
    """
    Transfere peso da origem para o destino (origem opcional).
    Se local_origem for informado, retira o peso da origem.
    """
    local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)

    # Retirar da origem, se necessário
    if local_origem:
        local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
        cursor.execute("""
            SELECT id, peso FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
              AND local_estoque = %s AND peso > 0
            ORDER BY data_registro FOR UPDATE
        """, (produtor_id, tipo_alho, classe_banco, local_origem_banco))
        entradas = cursor.fetchall()
        saldo = sum(float(e[1]) for e in entradas)
        if saldo < peso - 0.001:
            raise ValueError(f"Saldo insuficiente em {local_origem_banco} para {classe_banco}. "
                             f"Disponível: {saldo:.3f} kg, necessário: {peso:.3f} kg")
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

    # Inserir no destino
    entrada_id = None
    if peso > 0.001:
        cursor.execute("""
            INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (produtor_id, tipo_alho, classe_banco, round(peso, 4),
              local_destino_banco, horas_banca))
        entrada_id = cursor.fetchone()[0]
    return entrada_id

def registrar_entrada_direta(cursor, produtor_id, tipo_alho, classe_banco,
                              peso, local_destino, horas_banca=0):
    """
    Adiciona peso diretamente no destino, sem retirar de nenhuma origem.
    Usado para Indústria.
    """
    local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)
    cursor.execute("""
        INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (produtor_id, tipo_alho, classe_banco, round(peso, 4),
          local_destino_banco, horas_banca))
    return cursor.fetchone()[0]

def remover_perda_sem_registro(cursor, produtor_id, tipo_alho, classe_ui,
                                peso_perda, local_origem):
    """
    Remove peso_perda kg de uma classe específica da origem (FIFO dentro da classe)
    sem registrar na tabela perdas.
    """
    local_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
    classe_banco = CLASSES_MAP.get(classe_ui, classe_ui)

    cursor.execute("""
        SELECT id, peso FROM estoque
        WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
          AND local_estoque = %s AND peso > 0
        ORDER BY data_registro FOR UPDATE
    """, (produtor_id, tipo_alho, classe_banco, local_banco))
    entradas = cursor.fetchall()

    saldo = sum(float(e[1]) for e in entradas)
    if saldo < peso_perda - 0.001:
        raise ValueError(f"Saldo insuficiente em {local_banco} para a classe {classe_ui}. "
                         f"Disponível: {saldo:.3f} kg, perda: {peso_perda:.3f} kg")

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

# ─────────────────────────────────────────────────────────────────────────────
#  Consultas para o gerente (estatísticas robustas)
# ─────────────────────────────────────────────────────────────────────────────

def obter_estatisticas_gerais():
    stats = {
        'total_produtores': 0,
        'total_estoque_kg': 0,
        'estoque_classificacao': 0,
        'estoque_banca': 0,
        'estoque_toletagem': 0,
        'vendas_mes': 0,
        'pagamentos_mes': 0,
        'saldo_total': 0,
        'perdas_mes': 0,
    }
    conn = conectar_banco()
    if not conn:
        return stats

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM produtores")
        stats['total_produtores'] = cursor.fetchone()[0]
        cursor.close()
    except Exception as e:
        logger.error(f"Erro total_produtores: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE peso > 0")
        stats['total_estoque_kg'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro total_estoque_kg: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Classificação' AND peso>0")
        stats['estoque_classificacao'] = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Banca' AND peso>0")
        stats['estoque_banca'] = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(peso),0) FROM estoque WHERE local_estoque='Toletagem' AND peso>0")
        stats['estoque_toletagem'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro estoque por local: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM vendas
            WHERE DATE_TRUNC('month', data_venda) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        stats['vendas_mes'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro vendas_mes: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(valor_total),0) FROM pagamentos
            WHERE DATE_TRUNC('month', data_pagamento) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        stats['pagamentos_mes'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro pagamentos_mes: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(saldo),0) FROM creditos_produtor")
        stats['saldo_total'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro saldo_total: {e}")

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(peso_kg),0) FROM perdas
            WHERE DATE_TRUNC('month', data_perda) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        stats['perdas_mes'] = float(cursor.fetchone()[0])
        cursor.close()
    except Exception as e:
        logger.error(f"Erro perdas_mes: {e}")

    conn.close()
    return stats

# As demais funções de consulta (estoque_hierarquico, etc.) permanecem iguais às anteriores.
# Para brevidade, omiti aqui, mas você deve mantê-las do código original.
# ... (inserir aqui as funções obter_estoque_hierarquico, obter_estoque_por_produtor, etc.)

# ─────────────────────────────────────────────────────────────────────────────
#  Rotas e APIs (apenas as alterações principais)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/obter-saldos-todos', methods=['POST'])
def api_obter_saldos_todos():
    data = request.get_json(silent=True) or {}
    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local = data.get('local')
    if not all([produtor_id, tipo_alho, local]):
        return jsonify({'sucesso': False, 'mensagem': 'Parâmetros incompletos', 'saldos': {}})
    local_banco = MAPEAMENTO_LOCAL.get(local, local)
    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão', 'saldos': {}})
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT classe, COALESCE(SUM(peso), 0) FROM estoque
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
        logger.error(f"Erro ao buscar saldos: {e}")
        if conn:
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

    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem = data.get('local_origem')
    detalhes = data.get('detalhes', [])
    horas_banca = float(data.get('horas_banca', 0) or 0)

    if not produtor_id or not tipo_alho or not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Dados incompletos'}), 400

    # Separa os itens
    itens_destino = [d for d in detalhes if d.get('tipo') in ('classe', 'industria')]
    itens_perda = [d for d in detalhes if d.get('tipo') == 'perda']

    conn = conectar_banco()
    if not conn:
        return jsonify({'sucesso': False, 'mensagem': 'Erro de conexão'}), 500

    try:
        cursor = conn.cursor()
        total_entrou_destino = 0
        total_saiu_origem = 0

        # Processa itens que vão para o destino
        for item in itens_destino:
            classe_ui = item.get('classe')
            peso = float(item.get('peso', 0) or 0)
            if peso <= 0:
                continue

            if classe_ui == 'INDÚSTRIA':
                # Indústria: entrada direta no destino (não retira da origem)
                classe_banco = 'Indústria'
                entrada_id = registrar_entrada_direta(
                    cursor=cursor,
                    produtor_id=produtor_id,
                    tipo_alho=tipo_alho,
                    classe_banco=classe_banco,
                    peso=peso,
                    local_destino=local_destino,
                    horas_banca=horas_banca,
                )
                total_entrou_destino += peso
            else:
                # Classes normais: transferência (origem -> destino)
                classe_banco = CLASSES_MAP.get(classe_ui)
                if not classe_banco:
                    raise ValueError(f'Classe "{classe_ui}" não reconhecida')
                entrada_id = registrar_movimentacao(
                    cursor=cursor,
                    produtor_id=produtor_id,
                    tipo_alho=tipo_alho,
                    classe_banco=classe_banco,
                    peso=peso,
                    local_destino=local_destino,
                    horas_banca=horas_banca,
                    local_origem=local_origem,
                )
                total_entrou_destino += peso
                total_saiu_origem += peso

        # Processa perdas (apenas remover da origem)
        for item in itens_perda:
            classe_ui = item.get('classe')
            peso = float(item.get('peso', 0) or 0)
            if peso <= 0:
                continue
            remover_perda_sem_registro(
                cursor=cursor,
                produtor_id=produtor_id,
                tipo_alho=tipo_alho,
                classe_ui=classe_ui,
                peso_perda=peso,
                local_origem=local_origem,
            )
            total_saiu_origem += peso

        conn.commit()
        cursor.close()
        conn.close()

        msg = f'Registrado com sucesso! Entrou no destino: {total_entrou_destino:.2f} kg'
        if itens_perda:
            msg += f' | Perdas removidas: {sum(p["peso"] for p in itens_perda):.2f} kg'
        if horas_banca > 0:
            msg += f' | Horas: {horas_banca}'
        if local_origem and total_saiu_origem > 0:
            msg += f' | Origem: {local_origem}'

        return jsonify({'sucesso': True, 'mensagem': msg})

    except ValueError as e:
        conn.rollback()
        conn.close()
        logger.warning(f"Validação: {e}")
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 400
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro interno: {e}")
        return jsonify({'sucesso': False, 'mensagem': f'Erro interno: {str(e)}'}), 500

# ... (demais rotas: /, /login, /produtor, /registro-entrada, /gerente, /logout,
#      e as APIs do gerente permanecem inalteradas)

if __name__ == '__main__':
    criar_tabela_perdas()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
