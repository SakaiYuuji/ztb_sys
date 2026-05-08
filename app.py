import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import segno
import io
from google.oauth2.service_account import Credentials
import gspread
import re

st.set_page_config(page_title="Barbearia Elite - Agendamento", layout="centered")

# --- INICIALIZA A TRAVA DE SESSÃO LOCAL ---
if "horarios_bloqueados_sessao" not in st.session_state:
    st.session_state["horarios_bloqueados_sessao"] = []

# --- CONEXÃO SEGURA COM O GOOGLE SHEETS ---
@st.cache_resource
def conectar_banco():
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
        
        return client.open("Agendamentos Barbearia").sheet1
    except Exception as e:
        return None

planilha = conectar_banco()
if planilha is None:
    st.error("⚠️ Erro ao conectar com o banco de dados. Verifique a API do Drive e o Secrets.")
    st.stop()


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
    """MÉTODO BLINDADO: Lê por posição da coluna (Índice 2 e 3) e não pelo nome do cabeçalho"""
    try:
        valores = planilha.get_all_values()
        if len(valores) <= 1: # Se só tiver o cabeçalho
            return []
            
        ocupados = []
        for linha in valores[1:]: # Pula a linha 0 (cabeçalhos)
            if len(linha) > 3:
                # Índice 2 = Coluna Data, Índice 3 = Coluna Hora
                p_data = str(linha[2]).replace("'", "").strip()
                p_hora = str(linha[3]).replace("'", "").strip()
                
                if len(p_hora) >= 5:
                    p_hora = p_hora[:5]
                    
                if p_data == data_str:
                    ocupados.append(p_hora)
        return ocupados
    except Exception as e:
        return []

def gerar_horarios_disponiveis(data_selecionada):
    grade = []
    atual = datetime.strptime("08:00", "%H:%M")
    fim = datetime.strptime("18:30", "%H:%M")
    
    while atual <= fim:
        grade.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=30)
    
    data_str = data_selecionada.strftime("%d/%m/%Y")
    
    # Busca da Planilha
    ocupados_planilha = obter_horarios_ocupados(data_str)
    
    # Busca da Trava da Sessão Atual
    ocupados_sessao = [h for d, h in st.session_state["horarios_bloqueados_sessao"] if d == data_str]
    
    # Combina tudo que tá ocupado
    todos_ocupados = ocupados_planilha + ocupados_sessao
    
    agora = pegar_hora_local()
    # Se for o dia de hoje, tira os horários do passado
    if data_selecionada == agora.date():
        hora_atual = agora.strftime("%H:%M")
        grade = [h for h in grade if h > hora_atual]
    
    # Retorna apenas o que não estiver na lista combinada de ocupados
    return [h for h in grade if h not in todos_ocupados]


# --- ÁREA ADMINISTRATIVA (MENU LATERAL) ---
with st.sidebar:
    st.header("⚙️ Acesso Admin")
    admin_pass = st.text_input("Senha de Gerenciamento", type="password")
    
    if admin_pass == st.secrets["senha_admin"]:
        st.success("Acesso Liberado!")
        st.write("Configurações Rápidas:")
        novo_corte = st.number_input("Valor Corte Simples (R$)", value=30)
        novo_combo = st.number_input("Valor Combo (R$)", value=45)
        st.caption("No futuro, estes botões poderão alterar o preço do site automaticamente.")
        # Limpar cache de conexões para forçar o Streamlit a ler a planilha do zero
        if st.button("Limpar Cache de Conexão"):
            st.cache_resource.clear()
            st.session_state["horarios_bloqueados_sessao"] = []
            st.success("Cache Limpo!")
    elif admin_pass:
        st.error("Senha Incorreta")


# --- INTERFACE DO CLIENTE ---
st.title("✂️ Barbearia Elite")

if "agendamento_sucesso" in st.session_state:
    # --- TELA DE SUCESSO & PIX ---
    dados = st.session_state["agendamento_sucesso"]
    
    st.success(f"🎉 Fechado, {dados['nome']}! Horário reservado para {dados['data']} às {dados['hora']}.")
    st.info(f"O número cadastrado foi {dados['telefone']}.")
    
    st.divider()
    st.write("### 💸 Pagamento")
    tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
    
    with tab1:
        st.write("Tudo certo! Te aguardamos no horário marcado.")
        
    with tab2:
        st.write(f"Valor a pagar: **R$ {dados['preco']}**")
        chave_pix = "suachave@email.com"
        payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{dados['preco']}5802BR5910Barbearia6008Recife62070503***6304"
        
        qr = segno.make(payload_pix)
        buffer_qr = io.BytesIO()
        qr.save(buffer_qr, kind="png", scale=5)
        
        st.image(buffer_qr.getvalue(), caption="Escaneie o QR Code no app do seu banco")
        st.code(payload_pix, language="text")
        
    if st.button("Fazer um Novo Agendamento", use_container_width=True):
        del st.session_state["agendamento_sucesso"]
        st.rerun()

else:
    # --- TELA DE AGENDAMENTO ---
    st.subheader("Agende seu horário")
    
    nome = st.text_input("Seu Nome Completo")
    if nome:
    nome = re.sub(r'^[=+@-]', '', nome)
    
    telefone_input = st.text_input("WhatsApp (digite apenas números)", max_chars=11)

    col1, col2 = st.columns(2)
    with col1:
        data = st.date_input("Escolha a data", min_value=pegar_hora_local().date(), format="DD/MM/YYYY")

    # A FUNÇÃO AQUI VAI BUSCAR OS HORÁRIOS JÁ COM A TRAVA
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
            
            # Verificação final antes de salvar (Garante que dois não salvem juntos)
            if hora_escolhida in obter_horarios_ocupados(data_formatada):
                st.error("Putz! Alguém acabou de reservar esse horário. Escolha outro.")
            else:
                # TRAVA IMEDIATA NO STREAMLIT (Antes mesmo de ir pro Google)
                st.session_state["horarios_bloqueados_sessao"].append((data_formatada, hora_escolhida))

                registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
                # Salva com o apóstrofo para garantir texto puro na planilha
                planilha.append_row([
                    nome, 
                    telefone_formatado, 
                    f"'{data_formatada}", 
                    f"'{hora_escolhida}", 
                    servico, 
                    registro_now
                ])
                
                # Guarda dados em memória e recarrega a página IMEDIATAMENTE
                st.session_state["agendamento_sucesso"] = {
                    "nome": nome,
                    "telefone": telefone_formatado,
                    "data": data_formatada,
                    "hora": hora_escolhida,
                    "preco": preco
                }
                st.rerun()
