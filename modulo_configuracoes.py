# -*- coding: utf-8 -*-
"""
MÓDULO DE CONFIGURAÇÕES
- Comissão COPAR por kg (editável)
- Valor hora de banca (editável)
- Descontos extras configuráveis
- Dados da empresa
- Limpar banco (mantém produtores)
- Saldo e movimentações da Caixa COPAR
"""
from flask import render_template_string, jsonify, request, session
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


def verificar_acesso():
    if 'produtor_id' not in session:
        return False
    return session.get('tipo') in ('gerente', 'superadmin')


# ══════════════════════════════════════════════════════════════════════════
# CRIAÇÃO DE TABELAS
# ══════════════════════════════════════════════════════════════════════════

def criar_tabela_configuracoes():
    conn = conectar_banco()
    if not conn:
        return
    try:
        cur = conn.cursor()

        # Tabela de configurações (chave-valor)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave VARCHAR(50) PRIMARY KEY,
                valor TEXT
            )
        """)
        cur.execute("ALTER TABLE configuracoes ADD COLUMN IF NOT EXISTS descricao VARCHAR(200)")
        cur.execute("ALTER TABLE configuracoes ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        # Tabela de descontos configuráveis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS descontos_config (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                tipo VARCHAR(20) NOT NULL,
                valor DECIMAL(10,4) NOT NULL,
                ativo BOOLEAN DEFAULT TRUE,
                ordem INTEGER DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabela de caixa COPAR
        cur.execute("""
            CREATE TABLE IF NOT EXISTS caixa_copar (
                id SERIAL PRIMARY KEY,
                venda_id INTEGER,
                produtor_id INTEGER,
                tipo_movimento VARCHAR(20) NOT NULL DEFAULT 'comissao',
                peso_kg DECIMAL(10,4),
                valor DECIMAL(10,2) NOT NULL,
                descricao VARCHAR(200),
                data_movimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabela de horas de banca (por registro, não por classe)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS registros_horas_banca (
                id SERIAL PRIMARY KEY,
                produtor_id INTEGER,
                tipo_alho VARCHAR(50),
                local_origem VARCHAR(30),
                local_destino VARCHAR(30),
                horas DECIMAL(10,2) NOT NULL,
                registrado_por INTEGER,
                registrado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operador_nome VARCHAR(100),
                observacao TEXT
            )
        """)

        # Valores padrão
        valores_padrao = [
            ('comissao_por_kg', '0.30', 'Comissão COPAR por kg vendido (R$)'),
            ('valor_hora_banca', '16.00', 'Valor pago por hora de banca (R$)'),
            ('nome_empresa', 'COOPERATIVA AGRÍCOLA COPAR', 'Nome exibido em relatórios'),
            ('cnpj_empresa', '10.172.309/0001-12', 'CNPJ da cooperativa'),
            ('endereco_empresa', 'Rod. BR-116, Km 45 - Curitibanos/SC', 'Endereço'),
            ('telefone_empresa', '(49) 3241-0000', 'Telefone'),
        ]
        for chave, valor, desc in valores_padrao:
            cur.execute("""
                INSERT INTO configuracoes (chave, valor, descricao)
                VALUES (%s, %s, %s)
                ON CONFLICT (chave) DO NOTHING
            """, (chave, valor, desc))

        # Descontos padrão (só se não existir nenhum)
        cur.execute("SELECT COUNT(*) FROM descontos_config")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO descontos_config (nome, tipo, valor, ativo, ordem)
                VALUES ('Taxa Administrativa', 'percentual_valor', 2.00, TRUE, 1)
            """)

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Tabelas de configurações criadas/verificadas")
    except Exception as e:
        logger.error(f"Erro criar_tabela_configuracoes: {e}")


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════

def obter_configuracoes():
    conn = conectar_banco()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT chave, valor FROM configuracoes")
        config = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
        conn.close()
        return config
    except Exception as e:
        logger.error(f"Erro obter_configuracoes: {e}")
        return {}


def salvar_configuracao(chave, valor):
    conn = conectar_banco()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO configuracoes (chave, valor, atualizado_em)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor,
                                              atualizado_em = CURRENT_TIMESTAMP
        """, (chave, valor))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Erro salvar_configuracao: {e}")
        return False


def obter_comissao_por_kg():
    """Retorna o valor da comissão COPAR por kg (padrão 0.30)"""
    config = obter_configuracoes()
    try:
        return float(config.get('comissao_por_kg', '0.30'))
    except:
        return 0.30


def obter_valor_hora_banca():
    """Retorna o valor da hora de banca (padrão 16.00)"""
    config = obter_configuracoes()
    try:
        return float(config.get('valor_hora_banca', '16.00'))
    except:
        return 16.00


# ══════════════════════════════════════════════════════════════════════════
# DESCONTOS EXTRAS
# ══════════════════════════════════════════════════════════════════════════

def listar_descontos():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, tipo, valor, ativo, ordem
            FROM descontos_config ORDER BY ordem, id
        """)
        descontos = [{
            'id': r[0], 'nome': r[1], 'tipo': r[2],
            'valor': float(r[3]), 'ativo': r[4], 'ordem': r[5]
        } for r in cur.fetchall()]
        cur.close()
        conn.close()
        return descontos
    except Exception as e:
        logger.error(f"Erro listar_descontos: {e}")
        return []


def salvar_desconto(desconto_id, nome, tipo, valor, ativo, ordem=0):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        if desconto_id:
            cur.execute("""
                UPDATE descontos_config
                SET nome = %s, tipo = %s, valor = %s, ativo = %s, ordem = %s
                WHERE id = %s
            """, (nome, tipo, valor, ativo, ordem, desconto_id))
        else:
            cur.execute("""
                INSERT INTO descontos_config (nome, tipo, valor, ativo, ordem)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (nome, tipo, valor, ativo, ordem))
            desconto_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {'sucesso': True, 'id': desconto_id, 'mensagem': 'Desconto salvo!'}
    except Exception as e:
        logger.error(f"Erro salvar_desconto: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


def excluir_desconto(desconto_id):
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM descontos_config WHERE id = %s", (desconto_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {'sucesso': True, 'mensagem': 'Desconto excluído!'}
    except Exception as e:
        return {'sucesso': False, 'mensagem': str(e)}


# ══════════════════════════════════════════════════════════════════════════
# CAIXA COPAR
# ══════════════════════════════════════════════════════════════════════════

def registrar_comissao_copar(venda_id, produtor_id, peso_kg, valor, descricao=None):
    """Insere movimentação de comissão na caixa COPAR"""
    conn = conectar_banco()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO caixa_copar (venda_id, produtor_id, tipo_movimento,
                                     peso_kg, valor, descricao)
            VALUES (%s, %s, 'comissao', %s, %s, %s)
        """, (venda_id, produtor_id, peso_kg, valor, descricao or f'Comissão venda #{venda_id}'))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Erro registrar_comissao_copar: {e}")
        return False


def obter_saldo_copar():
    """Retorna o saldo total e o resumo mensal da caixa COPAR"""
    conn = conectar_banco()
    if not conn:
        return {'total': 0, 'por_mes': [], 'movimentos': []}
    try:
        cur = conn.cursor()

        # Saldo total
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN valor ELSE 0 END), 0) AS total_comissao,
                COALESCE(SUM(CASE WHEN tipo_movimento = 'ajuste' THEN valor ELSE 0 END), 0) AS total_ajustes,
                COALESCE(SUM(CASE WHEN tipo_movimento = 'retirada' THEN valor ELSE 0 END), 0) AS total_retiradas
            FROM caixa_copar
        """)
        r = cur.fetchone()
        total_comissao = float(r[0])
        total_ajustes = float(r[1])
        total_retiradas = float(r[2])
        saldo = total_comissao + total_ajustes - total_retiradas

        # Por mês (últimos 12 meses)
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', data_movimento), 'MM/YYYY') AS mes,
                   DATE_TRUNC('month', data_movimento) AS data_ord,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN valor ELSE 0 END), 0) AS comissao,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'ajuste' THEN valor ELSE 0 END), 0) AS ajustes,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'retirada' THEN valor ELSE 0 END), 0) AS retiradas,
                   COUNT(CASE WHEN tipo_movimento = 'comissao' THEN 1 END) AS qtd_vendas,
                   COALESCE(SUM(CASE WHEN tipo_movimento = 'comissao' THEN peso_kg ELSE 0 END), 0) AS peso
            FROM caixa_copar
            WHERE data_movimento >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', data_movimento)
            ORDER BY data_ord DESC
        """)
        por_mes = [{
            'mes': r[0],
            'comissao': float(r[2]),
            'ajustes': float(r[3]),
            'retiradas': float(r[4]),
            'saldo_mes': float(r[2]) + float(r[3]) - float(r[4]),
            'qtd_vendas': r[5],
            'peso': float(r[6]),
        } for r in cur.fetchall()]

        # Últimos movimentos (com detalhes)
        cur.execute("""
            SELECT c.id, c.data_movimento, c.tipo_movimento,
                   COALESCE(p.nome, '---') AS produtor,
                   c.peso_kg, c.valor, c.descricao, c.venda_id
            FROM caixa_copar c
            LEFT JOIN produtores p ON c.produtor_id = p.id
            ORDER BY c.data_movimento DESC
            LIMIT 100
        """)
        movimentos = [{
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
            'total_comissao': round(total_comissao, 2),
            'total_ajustes': round(total_ajustes, 2),
            'total_retiradas': round(total_retiradas, 2),
            'saldo': round(saldo, 2),
            'por_mes': por_mes,
            'movimentos': movimentos,
        }
    except Exception as e:
        logger.error(f"Erro obter_saldo_copar: {e}")
        return {'total': 0, 'por_mes': [], 'movimentos': [], 'saldo': 0}


def registrar_movimento_copar(tipo, valor, descricao='', produtor_id=None, peso_kg=None):
    """Insere ajuste ou retirada manual na caixa COPAR"""
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    if tipo not in ('ajuste', 'retirada'):
        return {'sucesso': False, 'mensagem': 'Tipo inválido'}
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO caixa_copar (tipo_movimento, valor, descricao, produtor_id, peso_kg)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (tipo, valor, descricao, produtor_id, peso_kg))
        mid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {'sucesso': True, 'id': mid, 'mensagem': f'{tipo.capitalize()} registrada!'}
    except Exception as e:
        logger.error(f"Erro registrar_movimento_copar: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


# ══════════════════════════════════════════════════════════════════════════
# LIMPAR BANCO (mantém produtores)
# ══════════════════════════════════════════════════════════════════════════

def limpar_dados_transacionais():
    """
    Remove TODOS os dados transacionais:
    - vendas, pagamentos, estoque, créditos, itens_pagos
    - caixa_copar
    - registros_horas_banca
    PRESERVA:
    - produtores (nome, cpf, matrícula)
    - configuracoes (comissão por kg, valor hora, dados da empresa)
    - descontos_config
    """
    conn = conectar_banco()
    if not conn:
        return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()

        # Conta antes
        counts = {}
        for tabela in ['vendas', 'pagamentos', 'estoque', 'caixa_copar', 'registros_horas_banca']:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tabela}")
                counts[tabela] = cur.fetchone()[0]
            except:
                counts[tabela] = 0

        # Apaga em ordem segura (FKs)
        for tabela in ['itens_pagos', 'creditos_produtor', 'pagamentos',
                       'caixa_copar', 'registros_horas_banca', 'vendas', 'estoque']:
            try:
                cur.execute(f"DELETE FROM {tabela}")
            except Exception as e:
                logger.warning(f"Não foi possível limpar {tabela}: {e}")

        # Reinicia sequences
        for tabela in ['vendas', 'pagamentos', 'estoque', 'creditos_produtor',
                       'itens_pagos', 'caixa_copar', 'registros_horas_banca']:
            try:
                cur.execute(f"ALTER SEQUENCE IF EXISTS {tabela}_id_seq RESTART WITH 1")
            except:
                pass

        conn.commit()
        cur.close()
        conn.close()

        return {
            'sucesso': True,
            'mensagem': 'Banco limpo com sucesso!',
            'detalhes': counts,
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro limpar_dados: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


# ══════════════════════════════════════════════════════════════════════════
# ROTAS FLASK
# ══════════════════════════════════════════════════════════════════════════

def registrar_rotas_configuracoes(app):
    criar_tabela_configuracoes()

    # ── Configurações gerais ─────────────────────────────────────────────
    @app.route('/api/configuracoes/obter')
    def api_config_obter():
        if not verificar_acesso():
            return jsonify({}), 403
        return jsonify(obter_configuracoes())

    @app.route('/api/configuracoes/salvar', methods=['POST'])
    def api_config_salvar():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        data = request.get_json()
        for chave, valor in data.items():
            salvar_configuracao(chave, str(valor))
        return jsonify({'sucesso': True, 'mensagem': 'Configurações salvas!'})

    # ── Descontos ────────────────────────────────────────────────────────
    @app.route('/api/descontos/listar')
    def api_descontos_listar():
        if not verificar_acesso():
            return jsonify([]), 403
        return jsonify(listar_descontos())

    @app.route('/api/descontos/salvar', methods=['POST'])
    def api_descontos_salvar():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(salvar_desconto(
            d.get('id'), d.get('nome', ''), d.get('tipo', 'percentual_valor'),
            float(d.get('valor', 0)), d.get('ativo', True), d.get('ordem', 0)
        ))

    @app.route('/api/descontos/excluir', methods=['POST'])
    def api_descontos_excluir():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(excluir_desconto(d.get('id')))

    # ── Caixa COPAR ──────────────────────────────────────────────────────
    @app.route('/api/copar/saldo')
    def api_copar_saldo():
        if not verificar_acesso():
            return jsonify({}), 403
        return jsonify(obter_saldo_copar())

    @app.route('/api/copar/movimento', methods=['POST'])
    def api_copar_movimento():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(registrar_movimento_copar(
            d.get('tipo', 'ajuste'), float(d.get('valor', 0)),
            d.get('descricao', ''), d.get('produtor_id'),
            d.get('peso_kg')
        ))

    # ── Limpar banco ─────────────────────────────────────────────────────
    @app.route('/api/admin/limpar-banco', methods=['POST'])
    def api_limpar_banco():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        d = request.get_json() or {}
        if d.get('confirmacao') != 'CONFIRMAR LIMPEZA':
            return jsonify({'sucesso': False, 'mensagem': 'Confirmação inválida'}), 400
        return jsonify(limpar_dados_transacionais())

    print("✅ Módulo de Configurações ativado!")


# ══════════════════════════════════════════════════════════════════════════
# EXPORTS para uso em outros módulos
# ══════════════════════════════════════════════════════════════════════════
__all__ = [
    'registrar_rotas_configuracoes',
    'obter_configuracoes',
    'salvar_configuracao',
    'obter_comissao_por_kg',
    'obter_valor_hora_banca',
    'listar_descontos',
    'registrar_comissao_copar',
    'obter_saldo_copar',
    'registrar_movimento_copar',
]
