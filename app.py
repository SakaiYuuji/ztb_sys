import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import segno
import io
from google.oauth2.service_account import Credentials
import gspread
import re

st.set_page_config(page_title="Barbearia Elite - Agendamento", layout="centered")

# --- CONEXÃO SEGURA COM O GOOGLE SHEETS ---
try:
    creds_dict = dict(st.secrets["gcp_service_account"])
    raw_key = creds_dict["private_key"]
    cleaned_lines = [line.strip() for line in raw_key.replace("\\n", "\n").split("\n") if line.strip()]
    creds_dict["private_key"] = "\n".join(cleaned_lines)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Nome exato da planilha que você acabou de criar no Google Drive
    NOME_PLANILHA = "13UgvP4l2EhgBNON2YGTALe8cwDXO5zCwgQzkynnwkk8" 
    planilha = client.open_by_key(NOME_PLANILHA).sheet1
except Exception as e:
    st.error(f"⚠️ Erro ao conectar com o banco de dados: {e}")
    st.stop() # Para a execução aqui para não dar 'NameError' lá embaixo


# --- FUNÇÕES DE LÓGICA E BLINDAGEM ---
def pegar_hora_local():
    return datetime.utcnow() - timedelta(hours=3)

def formatar_telefone(numero_cru):
    numeros = re.sub(r'\D', '', numero_cru)
    if len(numeros) == 11:
        return f"({numeros[:2]}) {numeros[2]} {numeros[3:7]}-{numeros[7:]}"
    elif len(numeros) == 10:
        return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
    return numero_cru

def obter_horarios_ocupados(data_str):
    try:
        registros = planilha.get_all_records()
        ocupados = []
        for linha in registros:
            p_data = str(linha.get("Data", "")).replace("'", "").strip()
            p_hora = str(linha.get("Hora", "")).replace("'", "").strip()
            
            if len(p_hora) >= 5:
                p_hora = p_hora[:5]
                
            if p_data == data_str:
                ocupados.append(p_hora)
        return ocupados
    except:
        return []

def gerar_horarios_disponiveis(data_selecionada):
    grade = []
    atual = datetime.strptime("08:00", "%H:%M")
    fim = datetime.strptime("18:30", "%H:%M")
    
    while atual <= fim:
        grade.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=30)
    
    data_str = data_selecionada.strftime("%d/%m/%Y")
    ocupados = obter_horarios_ocupados(data_str)
    
    agora = pegar_hora_local()
    if data_selecionada == agora.date():
        hora_atual = agora.strftime("%H:%M")
        grade = [h for h in grade if h > hora_atual]
    
    return [h for h in grade if h not in ocupados]


# --- INTERFACE DO APLICATIVO ---
st.title("✂️ Barbearia Elite")

# Lógica de Telas: Se o cliente acabou de agendar, mostramos o PIX. Se não, mostramos o formulário.
if "agendamento_sucesso" in st.session_state:
    # --- TELA DE SUCESSO & PIX ---
    dados = st.session_state["agendamento_sucesso"]
    
    st.success(f"🎉 Fechado, {dados['nome']}! Horário reservado para {dados['data']} às {dados['hora']}.")
    st.info(f"O número cadastrado foi {dados['telefone']}.")
    
    st.divider()
    st.write("### 💸 Pagamento")
    tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
    
    with tab1:
        st.write("Tudo certo! Pode acertar na hora do atendimento.")
        
    with tab2:
        st.write(f"Valor a pagar: **R$ {dados['preco']}**")
        
        chave_pix = "suachave@email.com"
        payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{dados['preco']}5802BR5910Barbearia6008Recife62070503***6304"
        
        qr = segno.make(payload_pix)
        buffer_qr = io.BytesIO()
        qr.save(buffer_qr, kind="png", scale=5)
        
        st.image(buffer_qr.getvalue(), caption="Escaneie o QR Code no app do seu banco")
        st.code(payload_pix, language="text")
        
    if st.button("Fazer um Novo Agendamento"):
        del st.session_state["agendamento_sucesso"]
        st.rerun()

else:
    # --- TELA DE AGENDAMENTO ---
    st.subheader("Agende seu horário")
    
    nome = st.text_input("Seu Nome Completo")
    telefone_input = st.text_input("WhatsApp (digite apenas números, ex: 81996962824)")

    col1, col2 = st.columns(2)
    with col1:
        data = st.date_input("Escolha a data", min_value=pegar_hora_local().date(), format="DD/MM/YYYY")

    opcoes = gerar_horarios_disponiveis(data)

    with col2:
        if opcoes:
            hora_escolhida = st.selectbox("Escolha o horário", opcoes)
        else:
            hora_escolhida = None
            st.error("Agenda lotada para este dia! 🛑")

    servico = st.selectbox("Serviço", ["Corte Simples - R$ 30", "Barba - R$ 20", "Combo - R$ 45"])
    preco = servico.split("R$ ")[1]

    st.divider()

    if st.button("Confirmar Agendamento", use_container_width=True):
        if not nome or not telefone_input:
            st.warning("⚠️ Preencha seu nome e telefone para continuar.")
        elif not hora_escolhida:
            st.warning("⚠️ Selecione uma data com horários disponíveis.")
        else:
            telefone_formatado = formatar_telefone(telefone_input)
            data_formatada = data.strftime("%d/%m/%Y")
            
            if hora_escolhida in obter_horarios_ocupados(data_formatada):
                st.error("Putz! Alguém acabou de reservar esse horário. Escolha outro.")
            else:
                registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
                planilha.append_row([
                    nome, 
                    telefone_formatado, 
                    f"'{data_formatada}", 
                    f"'{hora_escolhida}", 
                    servico, 
                    registro_now
                ])
                
                # Salva os dados na memória temporária e recarrega a página
                st.session_state["agendamento_sucesso"] = {
                    "nome": nome,
                    "telefone": telefone_formatado,
                    "data": data_formatada,
                    "hora": hora_escolhida,
                    "preco": preco
                }
                st.rerun()
