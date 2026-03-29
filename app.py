# ─── TRECHO A SUBSTITUIR em app.py ───────────────────────────────────────────
    # Substitua a função api_salvar_entrada e registrar_movimentacao pelas versões abaixo.
    # O restante do arquivo permanece igual.
    # ─────────────────────────────────────────────────────────────────────────────


def registrar_movimentacao(produtor_id, tipo_alho, classe, peso_liquido,
                            local_destino, horas_banca=0, quebra=0, local_origem=None):
    """
    Registra uma movimentação de estoque para UMA classe.

    Parâmetros:
        peso_liquido  – peso que vai ENTRAR no destino (já descontada a quebra).
        quebra        – peso que será perdido (registrado em `perdas`).
        local_origem  – se informado, retira (peso_liquido + quebra) do origem via FIFO.
    """
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão"
    try:
        cursor = conn.cursor()
        local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)

        if local_origem:
            local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
            total_retirar = peso_liquido + quebra          # bruto a sair do origem

            # Verificar saldo suficiente
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0)
                FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            saldo = float(cursor.fetchone()[0])

            if saldo < total_retirar - 0.001:   # tolerância de arredondamento
                cursor.close(); conn.close()
                return False, (
                    f"Saldo insuficiente em {local_origem_banco} para {classe}. "
                    f"Disponível: {saldo:.3f} kg, necessário: {total_retirar:.3f} kg"
                )

            # Retirar FIFO
            cursor.execute("""
                SELECT id, peso FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
                ORDER BY data_registro
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            entradas = cursor.fetchall()

            restante = total_retirar
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

            # Registrar perda se houver quebra
            if quebra > 0.001:
                cursor.execute("""
                    INSERT INTO perdas
                        (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (produtor_id, tipo_alho, classe, round(quebra, 4),
                      local_origem_banco, "Quebra na movimentação"))

        # Inserir no destino (peso líquido)
        entrada_id = None
        if peso_liquido > 0.001:
            cursor.execute("""
                INSERT INTO estoque
                    (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (produtor_id, tipo_alho, classe, round(peso_liquido, 4),
                  local_destino_banco, horas_banca))
            entrada_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()
        return True, entrada_id

    except Exception as e:
        logger.error(f"Erro ao registrar movimentação [{classe}]: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False, str(e)


@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """
    Payload esperado do frontend:
    {
        "produtor_id": 123,
        "tipo_alho":   "São Valentim",
        "local":       "banca",
        "local_origem":"Classificação",      # apenas banca/toletagem
        "horas_banca": 2,                    # apenas banca/toletagem
        "detalhes": [
            { "classe": "TIPO 2", "peso": 500, "quebra": 10 },
            { "classe": "TIPO 4", "peso": 800, "quebra": 0  },
            ...
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

    # ── Validações básicas ────────────────────────────
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})

    # ── Validações por role ───────────────────────────
    if role == 'classificacao':
        if local_destino != 'Classificação':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Classificação só registra entrada inicial.'})
        local_origem = None
        if horas_banca > 0:
            return jsonify({'sucesso': False,
                            'mensagem': 'Classificação não permite horas de banca.'})
        # Garantir quebra zero na classificação
        for item in detalhes:
            item['quebra'] = 0

    elif role == 'banca':
        if local_destino != 'banca':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Banca só transfere para Banca.'})
        if not local_origem or local_origem not in ('Classificação', 'Toletagem'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para Banca, a origem deve ser Classificação ou Toletagem.'})

    elif role == 'toletagem':
        if local_destino != 'toletagem':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Toletagem só transfere para Toletagem.'})
        if not local_origem or local_origem not in ('Classificação', 'Banca'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para Toletagem, a origem deve ser Classificação ou Banca.'})

    # ── Processar cada classe ─────────────────────────
    resultados = []
    erros      = []
    total_peso_liquido = 0
    total_quebra       = 0

    for item in detalhes:
        classe_ui = item.get('classe')
        peso      = float(item.get('peso',   0) or 0)
        quebra    = float(item.get('quebra', 0) or 0)

        if peso <= 0:
            continue

        # Validação por item
        if quebra < 0:
            erros.append({'classe': classe_ui, 'erro': 'Quebra não pode ser negativa'})
            continue
        if quebra > peso:
            erros.append({'classe': classe_ui,
                          'erro': f'Quebra ({quebra} kg) maior que o peso ({peso} kg)'})
            continue

        # Mapear classe
        classe_banco = CLASSES_MAP.get(classe_ui)
        if not classe_banco:
            erros.append({'classe': classe_ui, 'erro': f'Classe "{classe_ui}" não reconhecida'})
            continue

        peso_liquido = round(peso - quebra, 4)

        sucesso, resultado = registrar_movimentacao(
            produtor_id   = produtor_id,
            tipo_alho     = tipo_alho,
            classe        = classe_banco,
            peso_liquido  = peso_liquido,
            local_destino = local_destino,
            horas_banca   = horas_banca,
            quebra        = quebra,
            local_origem  = local_origem,
        )

        if sucesso:
            resultados.append({
                'classe':     classe_ui,
                'peso':       peso,
                'quebra':     quebra,
                'liquido':    peso_liquido,
                'entrada_id': resultado,
            })
            total_peso_liquido += peso_liquido
            total_quebra       += quebra
        else:
            erros.append({'classe': classe_ui, 'peso': peso, 'erro': resultado})

    # ── Resposta ──────────────────────────────────────
    if erros and not resultados:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro: {erros[0]["erro"]}',
            'erros': erros,
        }), 400

    if erros:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Alguns itens falharam: {erros[0]["erro"]}',
            'sucessos': resultados,
            'erros':    erros,
        }), 207

    msg = f'Registrado com sucesso! Peso líquido: {total_peso_liquido:.2f} kg'
    if total_quebra > 0:
        msg += f' (Quebra total: {total_quebra:.2f} kg)'
    if horas_banca > 0:
        msg += f' | Horas: {horas_banca}'
    if local_origem:
        msg += f' | Origem: {local_origem}'

    return jsonify({'sucesso': True, 'mensagem': msg, 'registros': resultados})
