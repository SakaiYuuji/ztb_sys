import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import segno
import io
from google.oauth2.service_account import Credentials
import gspread
import re

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Barbearia Elite", layout="centered")

@st.cache_resource
def conectar_planilha():
    creds_dict = dict(st.secrets["gcp_service_account"])
    raw_key = creds_dict["private_key"]
    cleaned_lines = [line.strip() for line in raw_key.replace("\\n", "\n").split("\n") if line.strip()]
    creds_dict["private_key"] = "\n".join(cleaned_lines)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Nome exato da planilha que você acabou de criar no Google Drive
    NOME_PLANILHA = "13UgvP4l2EhgBNON2YGTALe8cwDXO5zCwgQzkynnwkk8" 
    planilha = client.open_by_key(NOME_PLANILHA).sheet1

    planilha = conectar_planilha()

def pegar_hora_local():
    return datetime.utcnow() - timedelta(hours=3)

# --- LÓGICA DE FILTRAGEM RADICAL ---

def obter_horarios_ocupados(data_str):
    """Lê a planilha e limpa TUDO para garantir que '09:00' seja igual a '09:00'"""
    try:
        # Pega todos os dados de uma vez para ser mais rápido
        todos_os_dados = planilha.get_all_records()
        ocupados = []
        
        for linha in todos_os_dados:
            # Limpa a Data: remove apóstrofos e espaços
            p_data = str(linha.get("Data", "")).replace("'", "").strip()
            
            # Limpa a Hora: pega só os primeiros 5 caracteres (HH:MM)
            p_hora = str(linha.get("Hora", "")).replace("'", "").strip()
            if len(p_hora) >= 5:
                p_hora = p_hora[:5]
            
            if p_data == data_str:
                ocupados.append(p_hora)
        return ocupados
    except:
        return []

def gerar_horarios_disponiveis(data_selecionada):
    """Gera a grade e filtra contra os ocupados da planilha"""
    grade = []
    atual = datetime.strptime("08:00", "%H:%M")
    fim = datetime.strptime("18:30", "%H:%M")
    
    while atual <= fim:
        grade.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=30)
    
    data_str = data_selecionada.strftime("%d/%m/%Y")
    ocupados = obter_horarios_ocupados(data_str)
    
    # Se for hoje, remove horários que já passaram
    agora = pegar_hora_local()
    if data_selecionada == agora.date():
        hora_atual = agora.strftime("%H:%M")
        grade = [h for h in grade if h > hora_atual]
    
    # Filtro final: só o que não está na planilha
    return [h for h in grade if h not in ocupados]

# --- INTERFACE ---
st.title("✂️ Barbearia Elite")

nome = st.text_input("Nome Completo")
telefone = st.text_input("Telefone (apenas números)")

data = st.date_input("Data", min_value=pegar_hora_local().date(), format="DD/MM/YYYY")

# Busca horários disponíveis para a data selecionada
opcoes = gerar_horarios_disponiveis(data)

if opcoes:
    hora_escolhida = st.selectbox("Horários Disponíveis", opcoes)
    
    servico = st.selectbox("Serviço", ["Corte Simples - R$ 30", "Barba - R$ 20", "Combo - R$ 45"])
    preco = servico.split("R$ ")[1]

    if st.button("Confirmar Agendamento", use_container_width=True):
        if nome and telefone:
            data_formatada = data.strftime("%d/%m/%Y")
            
            # VERIFICAÇÃO DE ÚLTIMO SEGUNDO (Anti-duplicidade)
            # Antes de salvar, checa se alguém agendou enquanto o usuário preenchia
            if hora_escolhida in obter_horarios_ocupados(data_formatada):
                st.error("ERRO: Este horário acabou de ser ocupado! Selecione outro.")
            else:
                # Salva com apóstrofo para garantir formato Texto no Sheets
                registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
                planilha.append_row([
                    nome, 
                    telefone, 
                    f"'{data_formatada}", 
                    f"'{hora_escolhida}", 
                    servico, 
                    registro_now
                ])
                
                st.success(f"Agendado! O horário {hora_escolhida} foi removido da lista.")
                
                # O PULO DO GATO: Força o Streamlit a recarregar tudo
                # Isso faz a função gerar_horarios_disponiveis rodar de novo
                # e o horário que acabamos de salvar sumir imediatamente.
                st.rerun() 
        else:
            st.warning("Preencha nome e telefone.")
else:
    st.error("Desculpe, não há horários disponíveis para este dia.")
