import streamlit as st
import pandas as pd
from datetime import datetime, time
import segno # Para gerar QR Code
from gspread_pandas import Spread
import json
from google.oauth2.service_account import Credentials
import gspread

# Transforma a seção do Secrets diretamente em dicionário Python
creds_dict = dict(st.secrets["gcp_service_account"])

# Escopos necessários para acessar o Sheets e o Drive
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Autenticação direta e limpa
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

# Abre a planilha
planilha = client.open("Nome da Sua Planilha do Google").sheet1

# --- INTERFACE ---
st.title("✂️ Barbearia Elite")
st.subheader("Agende seu horário em segundos")

with st.form("agendamento_form"):
    nome = st.text_input("Seu Nome Completo")
    telefone = st.text_input("WhatsApp (com DDD)")
    
    col1, col2 = st.columns(2)
    with col1:
        data = st.date_input("Escolha a data", min_value=datetime.today())
    with col2:
        hora = st.time_input("Escolha o horário", value=time(9, 0))
        
    servico = st.selectbox("Serviço", ["Corte Simples - R$ 30", "Barba - R$ 20", "Combo - R$ 45"])
    preco = servico.split("R$ ")[1]

    submit = st.form_submit_button("Confirmar Agendamento")

if submit:
    if nome and telefone:
        # 1. Salva no Banco de Dados
        salvar_agendamento(nome, telefone, str(data), str(hora), servico)
        
        st.success(f"Horário reservado para {data} às {hora}!")
        
        # --- PAGAMENTO PIX ---
        st.divider()
        st.write("### 💸 Pagamento")
        tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
        
        with tab1:
            st.info("Tudo certo! Te esperamos na barbearia.")
            
        with tab2:
            st.write(f"Valor: R$ {preco}")
            # Gera um QR Code estático (Simplificado)
            # Para um sistema real, use a chave PIX da barbearia
            chave_pix = "suachave@email.com"
            payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{preco}5802BR5910Barbearia6008Recife62070503***6304"
            
            qr = segno.make(payload_pix)
            st.image(qr.to_pil(scale=5), caption="Escaneie para pagar")
            st.code(payload_pix, language="text")
            st.caption("Após pagar, envie o comprovante pelo WhatsApp.")
    else:
        st.error("Por favor, preencha todos os campos.")
