# ========== FUNÇÕES PARA O GERENTE ==========

def obter_estatisticas_gerais():
    """Retorna estatísticas para o dashboard do gerente"""
    conn = conectar_banco()
    if not conn:
        return {
            'total_produtores': 0,
            'total_estoque_kg': 0,
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
        
        print(f"ESTATÍSTICAS: produtores={total_produtores}, estoque={total_estoque_kg}, vendas_mes={vendas_mes}, pagamentos_mes={pagamentos_mes}")  # Debug
        
        return {
            'total_produtores': total_produtores,
            'total_estoque_kg': total_estoque_kg,
            'vendas_mes': vendas_mes,
            'pagamentos_mes': pagamentos_mes,
            'saldo_total': saldo_total,
            'perdas_mes': perdas_mes
        }
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        print(f"ERRO: {e}")  # Debug
        return {
            'total_produtores': 0,
            'total_estoque_kg': 0,
            'vendas_mes': 0,
            'pagamentos_mes': 0,
            'saldo_total': 0,
            'perdas_mes': 0
        }

def obter_estoque_por_produtor():
    """Retorna estoque agrupado por produtor, tipo e classe"""
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
        print(f"ESTOQUE PRODUTOR: {len(estoque)} registros encontrados")  # Debug
        return estoque
    except Exception as e:
        logger.error(f"Erro ao buscar estoque por produtor: {e}")
        print(f"ERRO ESTOQUE: {e}")  # Debug
        return []

def obter_vendas_recentes(limite=50):
    """Retorna as vendas do MÊS ATUAL"""
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
        print(f"VENDAS RECENTES: {len(vendas)} registros encontrados")  # Debug
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas recentes: {e}")
        print(f"ERRO VENDAS: {e}")  # Debug
        return []

def obter_pagamentos_recentes(limite=50):
    """Retorna os pagamentos do MÊS ATUAL"""
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
        print(f"PAGAMENTOS RECENTES: {len(pagamentos)} registros encontrados")  # Debug
        return pagamentos
    except Exception as e:
        logger.error(f"Erro ao buscar pagamentos recentes: {e}")
        print(f"ERRO PAGAMENTOS: {e}")  # Debug
        return []

def obter_estoque_por_tipo():
    """Retorna total em estoque agrupado por tipo de alho (para gráfico)"""
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
        print(f"ESTOQUE POR TIPO: {len(estoque)} tipos encontrados")  # Debug
        return estoque
    except Exception as e:
        logger.error(f"Erro ao buscar estoque por tipo: {e}")
        print(f"ERRO ESTOQUE TIPO: {e}")  # Debug
        return []

def obter_vendas_por_mes():
    """Retorna vendas dos últimos 6 meses (valor total)"""
    conn = conectar_banco()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                TO_CHAR(DATE_TRUNC('month', data_venda), 'Mon/YYYY') as mes,
                COALESCE(SUM(valor_total), 0) as total_vendas
            FROM vendas
            WHERE data_venda >= CURRENT_DATE - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', data_venda)
            ORDER BY DATE_TRUNC('month', data_venda)
        """)
        vendas = [{'mes': r[0], 'total': float(r[1])} for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        print(f"VENDAS POR MÊS: {len(vendas)} meses encontrados")  # Debug
        return vendas
    except Exception as e:
        logger.error(f"Erro ao buscar vendas por mês: {e}")
        print(f"ERRO VENDAS MES: {e}")  # Debug
        return []

def obter_perdas_recentes(limite=50):
    """Retorna as perdas do MÊS ATUAL"""
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
        print(f"PERDAS RECENTES: {len(perdas)} registros encontrados")  # Debug
        return perdas
    except Exception as e:
        logger.error(f"Erro ao buscar perdas recentes: {e}")
        print(f"ERRO PERDAS: {e}")  # Debug
        return []
