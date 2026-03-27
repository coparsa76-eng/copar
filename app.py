#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web - Sistema completo com movimentação entre locais, horas e quebra
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
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1)
)

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require'
)

# Mapeamento dos locais
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
    """Cria a tabela de perdas se não existir"""
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
    """Lê o valor da hora banca da tabela configuracoes"""
    conn = conectar_banco()
    if not conn:
        return 16.00  # valor padrão
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT valor FROM configuracoes WHERE chave = 'descontos_padrao'")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            import json
            config = json.loads(row[0])
            return float(config.get('valor_hora_banca', 16.00))
        return 16.00
    except Exception as e:
        logger.error(f"Erro ao ler valor hora banca: {e}")
        return 16.00

# ========== FUNÇÕES DE CONSULTA ==========

def buscar_produtor_por_matricula(matricula):
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
            'nome': 'Administrador - Registro de Entrada',
            'matricula': 'copar10',
            'especial': True,
            'tipo': 'entrada'
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
                'especial': False
            }
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

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

# ========== FUNÇÃO DE REGISTRO COM MOVIMENTAÇÃO ==========

def registrar_movimentacao(produtor_id, tipo_alho, classe, peso_movido, local_destino, horas_banca=0, quebra=0, local_origem=None):
    """
    Registra uma movimentação de estoque.
    - Se local_origem for informado, dá baixa nesse local (respeitando FIFO).
    - Se quebra > 0, subtrai esse valor do local_origem e registra na tabela perdas.
    - Se horas_banca > 0, registra no novo lote (apenas se destino for Banca).
    - Insere o peso líquido (peso_movido - quebra) no local_destino.
    """
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão"

    try:
        cursor = conn.cursor()

        # 1. Se há origem, dar baixa
        if local_origem:
            # Verificar saldo disponível
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0)
                FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                AND local_estoque = %s AND peso > 0
            """, (produtor_id, tipo_alho, classe, local_origem))
            saldo = float(cursor.fetchone()[0])
            total_retirar = peso_movido + quebra
            if saldo < total_retirar:
                return False, f"Saldo insuficiente em {local_origem}. Disponível: {saldo:.2f} kg, necessário: {total_retirar:.2f} kg"

            # Dar baixa FIFO (primeiro a entrar, primeiro a sair)
            cursor.execute("""
                SELECT id, peso FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                AND local_estoque = %s AND peso > 0
                ORDER BY data_registro
            """, (produtor_id, tipo_alho, classe, local_origem))
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
            if peso_restante > 0:
                return False, "Erro interno: não foi possível dar baixa completa"

            # Registrar quebra, se houver
            if quebra > 0:
                cursor.execute("""
                    INSERT INTO perdas (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (produtor_id, tipo_alho, classe, quebra, local_origem, "Quebra na movimentação"))

        # 2. Inserir no local de destino (se houver peso líquido)
        if peso_movido - quebra > 0:
            local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)
            horas_banca_final = horas_banca if local_destino == 'banca' else 0
            cursor.execute("""
                INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (produtor_id, tipo_alho, classe, peso_movido - quebra, local_destino_banco, horas_banca_final))
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

# ========== FUNÇÕES AUXILIARES ==========

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

# ========== FUNÇÕES PARA O GERENTE ==========

def obter_estatisticas_gerais():
    conn = conectar_banco()
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM produtores")
        total_produtores = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(peso), 0) FROM estoque WHERE peso > 0")
        total_estoque_kg = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(valor_total), 0) FROM vendas WHERE date(data_venda) = CURRENT_DATE")
        vendas_hoje = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(valor_total), 0) FROM pagamentos WHERE date(data_pagamento) = CURRENT_DATE")
        pagamentos_hoje = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(saldo), 0) FROM creditos_produtor")
        saldo_total = float(cursor.fetchone()[0])
        cursor.execute("SELECT COALESCE(SUM(peso_kg), 0) FROM perdas WHERE date(data_perda) = CURRENT_DATE")
        perdas_hoje = float(cursor.fetchone()[0])
        cursor.close()
        conn.close()
        return {
            'total_produtores': total_produtores,
            'total_estoque_kg': total_estoque_kg,
            'vendas_hoje': vendas_hoje,
            'pagamentos_hoje': pagamentos_hoje,
            'saldo_total': saldo_total,
            'perdas_hoje': perdas_hoje
        }
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        return {}

def obter_estoque_por_produtor():
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.nome as produtor, e.tipo_alho, e.classe, SUM(e.peso) as total_peso, e.local_estoque
            FROM estoque e
            JOIN produtores p ON e.produtor_id = p.id
            WHERE e.peso > 0
            GROUP BY p.nome, e.tipo_alho, e.classe, e.local_estoque
            ORDER BY p.nome, e.tipo_alho, e.classe
        """)
        estoque = [{'produtor': r[0], 'tipo_alho': r[1], 'classe': r[2], 'peso': float(r[3]), 'local': r[4]} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return estoque
    except Exception as e:
        logger.error(f"Erro ao buscar estoque por produtor: {e}")
        return []

def obter_vendas_recentes(limite=20):
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
            ORDER BY v.data_venda DESC
            LIMIT %s
        """, (limite,))
        vendas = []
        for r in cursor.fetchall():
            vendas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'valor_total': float(r[5]), 'valor_produtor': float(r[6]),
                'status': r[7], 'data': r[8].strftime("%d/%m/%Y %H:%M") if r[8] else ""
            })
        cursor.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas recentes: {e}")
        return []

def obter_pagamentos_recentes(limite=20):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pa.id, p.nome as produtor, pa.valor_total, pa.forma_pagamento, pa.data_pagamento
            FROM pagamentos pa
            JOIN produtores p ON pa.produtor_id = p.id
            ORDER BY pa.data_pagamento DESC
            LIMIT %s
        """, (limite,))
        pagamentos = []
        for r in cursor.fetchall():
            pagamentos.append({
                'id': r[0], 'produtor': r[1], 'valor': float(r[2]), 'forma': r[3],
                'data': r[4].strftime("%d/%m/%Y %H:%M") if r[4] else ""
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
            SELECT DATE_TRUNC('month', data_venda) as mes, COALESCE(SUM(valor_total), 0) as total_vendas
            FROM vendas
            WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', data_venda)
            ORDER BY mes
        """)
        vendas = [{'mes': r[0].strftime("%b/%Y") if r[0] else "", 'total': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas por mês: {e}")
        return []

def obter_perdas_recentes(limite=20):
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, pr.nome as produtor, p.tipo_alho, p.classe, p.peso_kg, p.local_origem, p.data_perda, p.motivo
            FROM perdas p
            JOIN produtores pr ON p.produtor_id = pr.id
            ORDER BY p.data_perda DESC
            LIMIT %s
        """, (limite,))
        perdas = []
        for r in cursor.fetchall():
            perdas.append({
                'id': r[0], 'produtor': r[1], 'tipo_alho': r[2], 'classe': r[3],
                'peso': float(r[4]), 'local_origem': r[5],
                'data': r[6].strftime("%d/%m/%Y %H:%M") if r[6] else "",
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
        if session.get('acesso_especial'):
            if session.get('tipo') == 'gerente':
                return redirect(url_for('gerente'))
            return redirect(url_for('registro_entrada'))
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
            if session['acesso_especial']:
                if session['tipo'] == 'gerente':
                    return redirect(url_for('gerente'))
                else:
                    return redirect(url_for('registro_entrada'))
            else:
                return redirect(url_for('produtor'))
        else:
            return render_template('login.html', erro='Matrícula não encontrada')
    return render_template('login.html', erro=None)

@app.route('/produtor')
def produtor():
    if 'produtor_id' not in session or session.get('acesso_especial'):
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
    if 'produtor_id' not in session or not session.get('acesso_especial') or session.get('tipo') == 'gerente':
        return redirect(url_for('login'))
    return render_template('registro_entrada.html', valor_hora_banca=obter_valor_hora_banca())

@app.route('/gerente')
def gerente():
    if 'produtor_id' not in session or not session.get('acesso_especial') or session.get('tipo') != 'gerente':
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

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    data = request.get_json()
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400

    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local_destino = data.get('local', 'Classificação')
    detalhes = data.get('detalhes', [])
    horas_banca = data.get('horas_banca', 0)
    quebra_global = data.get('quebra', 0)

    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})

    # Mapeamento das classes
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

    # Determinar local de origem, se houver movimentação
    local_origem = None
    if local_destino == 'banca':
        local_origem = 'Classificação'
    elif local_destino == 'toletagem':
        local_origem = 'Banca'

    # Para cada classe
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

        if local_origem is None:
            # Entrada inicial (destino = Classificação)
            sucesso, resultado = registrar_movimentacao(
                produtor_id, tipo_alho, classe_destino, peso,
                local_destino, horas_banca=0, quebra=0, local_origem=None
            )
        else:
            # Movimentação: peso é o total retirado da origem, que inclui a quebra?
            # A quebra é global para toda a entrada. Vamos tratar: o usuário informa a quebra total (kg) que deve ser subtraída do total movido.
            # Distribuir a quebra proporcionalmente ao peso de cada classe? Para simplicidade, aplicamos a quebra total a todas as classes?
            # Melhor: a quebra é informada por classe? O usuário pode informar um único valor para toda a operação.
            # Vamos usar a quebra_global como total a ser descontado do somatório de pesos.
            # Vamos calcular proporcionalmente.
            if quebra_global > 0 and peso_total_movido > 0:
                quebra_proporcional = peso * quebra_global / peso_total_movido
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

    return jsonify({
        'sucesso': True,
        'mensagem': f'Registro realizado com sucesso! Total movido: {peso_total_movido - quebra_global:.2f} Kg' +
                    (f' (Quebra: {quebra_global:.2f} Kg)' if quebra_global > 0 else ''),
        'registros': resultados
    })

# APIs para o gerente
@app.route('/api/gerente/estatisticas')
def api_gerente_estatisticas():
    return jsonify(obter_estatisticas_gerais())

@app.route('/api/gerente/estoque-produtor')
def api_gerente_estoque_produtor():
    return jsonify(obter_estoque_por_produtor())

@app.route('/api/gerente/vendas-recentes')
def api_gerente_vendas_recentes():
    limite = request.args.get('limite', 20, type=int)
    return jsonify(obter_vendas_recentes(limite))

@app.route('/api/gerente/pagamentos-recentes')
def api_gerente_pagamentos_recentes():
    limite = request.args.get('limite', 20, type=int)
    return jsonify(obter_pagamentos_recentes(limite))

@app.route('/api/gerente/estoque-por-tipo')
def api_gerente_estoque_por_tipo():
    return jsonify(obter_estoque_por_tipo())

@app.route('/api/gerente/vendas-por-mes')
def api_gerente_vendas_por_mes():
    return jsonify(obter_vendas_por_mes())

@app.route('/api/gerente/perdas-recentes')
def api_gerente_perdas_recentes():
    limite = request.args.get('limite', 20, type=int)
    return jsonify(obter_perdas_recentes(limite))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Criar tabela de perdas se necessário
    criar_tabela_perdas()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
