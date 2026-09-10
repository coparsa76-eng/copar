# -*- coding: utf-8 -*-
"""
MÓDULO DE CONFIGURAÇÕES - Descontos, hora de banca e gestão de dados
"""
from flask import render_template_string, jsonify, request, session
import psycopg
import logging

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

# ── TABELA DE CONFIGURAÇÕES ─────────────────────────────────────────────────
def criar_tabela_configuracoes():
    conn = conectar_banco()
    if not conn: return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave VARCHAR(50) PRIMARY KEY,
                valor TEXT,
                descricao VARCHAR(200),
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de descontos configuráveis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS descontos_config (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('percentual', 'valor')),
                valor DECIMAL(10,4) NOT NULL,
                ativo BOOLEAN DEFAULT TRUE,
                ordem INTEGER DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Valores padrão
        valores_padrao = [
            ('valor_hora_banca', '16.00', 'Valor pago por hora de banca (R$)'),
            ('comissao_venda_pct', '10.00', 'Comissão da cooperativa sobre vendas (%)'),
            ('nome_empresa', 'COOPERATIVA AGRÍCOLA COPAR', 'Nome exibido em relatórios'),
            ('cnpj_empresa', '10.172.309/0001-12', 'CNPJ da cooperativa'),
            ('endereco_empresa', 'Rod. BR-116, Km 45 - Curitibanos/SC', 'Endereço da cooperativa'),
            ('telefone_empresa', '(49) 3241-0000', 'Telefone da cooperativa'),
        ]
        
        for chave, valor, desc in valores_padrao:
            cur.execute("""
                INSERT INTO configuracoes (chave, valor, descricao)
                VALUES (%s, %s, %s)
                ON CONFLICT (chave) DO NOTHING
            """, (chave, valor, desc))
        
        # Descontos padrão (se não existirem)
        cur.execute("SELECT COUNT(*) FROM descontos_config")
        if cur.fetchone()[0] == 0:
            descontos_padrao = [
                ('Comissão COPAR', 'percentual', 10.00, True, 1),
                ('Taxa Administrativa', 'percentual', 2.00, True, 2),
            ]
            for nome, tipo, valor, ativo, ordem in descontos_padrao:
                cur.execute("""
                    INSERT INTO descontos_config (nome, tipo, valor, ativo, ordem)
                    VALUES (%s, %s, %s, %s, %s)
                """, (nome, tipo, valor, ativo, ordem))
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Tabelas de configurações criadas")
    except Exception as e:
        logger.error(f"Erro criar_tabela_configuracoes: {e}")

# ── CONFIGURAÇÕES ───────────────────────────────────────────────────────────
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
    except Exception as e:
        logger.error(f"Erro obter_configuracoes: {e}")
        return {}

def salvar_configuracao(chave, valor):
    conn = conectar_banco()
    if not conn: return False
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

# ── DESCONTOS ───────────────────────────────────────────────────────────────
def listar_descontos():
    conn = conectar_banco()
    if not conn: return []
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
    if not conn: return {'sucesso': False, 'mensagem': 'Erro de conexão'}
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
    if not conn: return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM descontos_config WHERE id = %s", (desconto_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {'sucesso': True, 'mensagem': 'Desconto excluído!'}
    except Exception as e:
        return {'sucesso': False, 'mensagem': str(e)}

# ── CÁLCULO DE DESCONTOS ────────────────────────────────────────────────────
def calcular_descontos(valor_bruto):
    """Calcula total de descontos sobre um valor"""
    descontos = listar_descontos()
    total_percentual = sum(d['valor'] for d in descontos if d['ativo'] and d['tipo'] == 'percentual')
    total_fixo = sum(d['valor'] for d in descontos if d['ativo'] and d['tipo'] == 'valor')
    
    valor_pct = valor_bruto * (total_percentual / 100)
    desconto_total = valor_pct + total_fixo
    valor_liquido = valor_bruto - desconto_total
    
    return {
        'valor_bruto': valor_bruto,
        'total_percentual': total_percentual,
        'total_fixo': total_fixo,
        'desconto_pct': valor_pct,
        'desconto_total': desconto_total,
        'valor_liquido': max(0, valor_liquido),
        'detalhes': descontos
    }

# ── HORA DE BANCA ───────────────────────────────────────────────────────────
def calcular_horas_banca_pendentes(produtor_id):
    """Calcula horas de banca totais do produtor no estoque atual"""
    conn = conectar_banco()
    if not conn: return 0
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(horas_banca), 0)
            FROM estoque
            WHERE produtor_id = %s AND peso > 0
        """, (produtor_id,))
        total = float(cur.fetchone()[0])
        cur.close()
        conn.close()
        return total
    except Exception as e:
        logger.error(f"Erro calcular_horas_banca: {e}")
        return 0

# ── LIMPAR BANCO ────────────────────────────────────────────────────────────
def limpar_dados_transacionais():
    """Remove TODOS os dados de vendas, pagamentos, estoque e créditos.
    PRESERVA apenas: produtores (nome, cpf, matrícula) e configurações."""
    conn = conectar_banco()
    if not conn: return {'sucesso': False, 'mensagem': 'Erro de conexão'}
    try:
        cur = conn.cursor()
        
        # Conta registros antes de limpar (para relatório)
        cur.execute("SELECT COUNT(*) FROM vendas")
        qtd_vendas = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM pagamentos")
        qtd_pagamentos = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM estoque")
        qtd_estoque = cur.fetchone()[0]
        
        # Limpa em ordem (respeitando FKs)
        cur.execute("DELETE FROM itens_pagos")
        cur.execute("DELETE FROM creditos_produtor")
        cur.execute("DELETE FROM pagamentos")
        cur.execute("DELETE FROM vendas")
        cur.execute("DELETE FROM estoque")
        
        # Reinicia as sequences
        for tabela in ['vendas', 'pagamentos', 'estoque', 'creditos_produtor', 'itens_pagos']:
            try:
                cur.execute(f"ALTER SEQUENCE IF EXISTS {tabela}_id_seq RESTART WITH 1")
            except: pass
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            'sucesso': True,
            'mensagem': f'Banco limpo com sucesso!',
            'detalhes': {
                'vendas_removidas': qtd_vendas,
                'pagamentos_removidos': qtd_pagamentos,
                'registros_estoque_removidos': qtd_estoque
            }
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Erro limpar_dados: {e}")
        return {'sucesso': False, 'mensagem': str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════════════════════

def registrar_rotas_configuracoes(app):
    criar_tabela_configuracoes()
    
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
            d.get('id'), d.get('nome', ''), d.get('tipo', 'percentual'),
            float(d.get('valor', 0)), d.get('ativo', True), d.get('ordem', 0)
        ))
    
    @app.route('/api/descontos/excluir', methods=['POST'])
    def api_descontos_excluir():
        if not verificar_acesso():
            return jsonify({'sucesso': False}), 403
        d = request.get_json()
        return jsonify(excluir_desconto(d.get('id')))
    
    @app.route('/api/descontos/calcular', methods=['POST'])
    def api_descontos_calcular():
        if not verificar_acesso():
            return jsonify({}), 403
        d = request.get_json()
        return jsonify(calcular_descontos(float(d.get('valor_bruto', 0))))
    
    @app.route('/api/admin/limpar-banco', methods=['POST'])
    def api_limpar_banco():
        if not verificar_acesso():
            return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403
        # Dupla confirmação no backend
        d = request.get_json() or {}
        if d.get('confirmacao') != 'CONFIRMAR LIMPEZA':
            return jsonify({'sucesso': False, 'mensagem': 'Confirmação inválida'}), 400
        return jsonify(limpar_dados_transacionais())
    
    print("✅ Módulo de Configurações carregado!")
