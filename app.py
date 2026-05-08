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


# --- FUNÇÕES DE NORMALIZAÇÃO DE DADOS (COMPATIBILIDADE RETROATIVA) ---

def normalizar_data(data_str):
    """Converte qualquer formato de data (2026/05/08 ou 2026-05-08) para o padrão 08/05/2026"""
    data_str = data_str.replace("'", "").strip()
    for formato in ["%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(data_str, formato)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return data_str

def normalizar_hora(hora_str):
    """Converte horas com segundos (15:30:00) ou sem zero à esquerda (9:30) para 09:30 ou 15:30"""
    hora_str = hora_str.replace("'", "").strip()
    if ":" in hora_str:
        partes = hora_str.split(":")
        if len(partes) >= 2:
            h = partes[0].zfill(2)
            m = partes[1].zfill(2)
            return f"{h}:{m}"
    return hora_str


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
    """MÉTODO BLINDADO: Lê por posição da coluna e autodetecta se existe cabeçalho na linha 1"""
    try:
        valores = planilha.get_all_values()
        if len(valores) == 0:
            return []
            
        # Autodetecção inteligente de cabeçalho
        primeira_celula = str(valores[0][0]).strip().lower()
        tem_cabecalho = primeira_celula in ["nome", "cliente", "client"]
        inicio = 1 if tem_cabecalho else 0
            
        ocupados = []
        target_data = normalizar_data(data_str)
        
        for linha in valores[inicio:]:
            if len(linha) > 3:
                p_data = normalizar_data(str(linha[2]))
                p_hora = normalizar_hora(str(linha[3]))
                    
                if p_data == target_data:
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
    ocupados_sessao = [h for d, h in st.session_state["horarios_bloqueados_sessao"] if normalizar_data(d) == normalizar_data(data_str)]
    
    # Combina tudo que tá ocupado
    todos_ocupados = ocupados_planilha + ocupados_sessao
    
    agora = pegar_hora_local()
    # Se for o dia de hoje, tira os horários do passado
    if data_selecionada == agora.date():
        hora_atual = agora.strftime("%H:%M")
        grade = [h for h in grade if h > hora_atual]
    
    # Retorna apenas o que não estiver na lista combinada de ocupados
    return [h for h in grade if h not in todos_ocupados]

def buscar_todos_dados_para_painel():
    """MÉTODO BLINDADO COM AUTO-DETECÇÃO DE CABEÇALHO: Lê os dados do Sheets sem depender de cabeçalhos fixos"""
    try:
        valores = planilha.get_all_values()
        if len(valores) == 0:
            return pd.DataFrame()
            
        # Autodetecção inteligente de cabeçalho
        primeira_celula = str(valores[0][0]).strip().lower()
        tem_cabecalho = primeira_celula in ["nome", "cliente", "client"]
        inicio = 1 if tem_cabecalho else 0
            
        dados_limpos = []
        for linha in valores[inicio:]:
            if len(linha) >= 5:
                nome_val = str(linha[0]).strip()
                tel_val = str(linha[1]).strip()
                data_val = normalizar_data(str(linha[2]))
                hora_val = normalizar_hora(str(linha[3]))
                serv_val = str(linha[4]).strip()
                
                # Se houver a coluna de Data de Registro na planilha, pegamos ela também
                reg_val = str(linha[5]).strip() if len(linha) >= 6 else ""
                
                dados_limpos.append({
                    "Nome": nome_val,
                    "Telefone": tel_val,
                    "Data": data_val,
                    "Hora": hora_val,
                    "Serviço": serv_val,
                    "Data Registro": reg_val
                })
        return pd.DataFrame(dados_limpos)
    except Exception as e:
        return pd.DataFrame()


# --- MENU LATERAL (NAVEGAÇÃO E LOGIN ADMIN) ---
with st.sidebar:
    st.title("✂️ Menu Principal")
    aba_selecionada = st.radio("Ir para:", ["Agendar Horário", "Painel do Barbeiro (Admin)"])
    
    st.divider()
    
    acesso_admin_liberado = False
    if aba_selecionada == "Painel do Barbeiro (Admin)":
        st.header("⚙️ Acesso Admin")
        admin_pass = st.text_input("Senha de Gerenciamento", type="password")
        
        if admin_pass == st.secrets["senha_admin"]:
            st.success("Acesso Liberado!")
            acesso_admin_liberado = True
            
            if st.button("Sincronizar Banco de Dados"):
                st.cache_resource.clear()
                st.session_state["horarios_bloqueados_sessao"] = []
                st.success("Banco sincronizado!")
        elif admin_pass:
            st.error("Senha Incorreta")


# =======================================================
# INTERFACE DO CLIENTE
# =======================================================
if aba_selecionada == "Agendar Horário":
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
                    st.session_state["horarios_bloqueados_sessao"].append((data_formatada, hora_escolhida))

                    registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
                    planilha.append_row([
                        nome, 
                        telefone_formatado, 
                        f"'{data_formatada}", 
                        f"'{hora_escolhida}", 
                        servico, 
                        registro_now
                    ])
                    
                    st.session_state["agendamento_sucesso"] = {
                        "nome": nome,
                        "telefone": telefone_formatado,
                        "data": data_formatada,
                        "hora": hora_escolhida,
                        "preco": preco
                    }
                    st.rerun()

# =======================================================
# DASHBOARD DO BARBEIRO
# =======================================================
elif aba_selecionada == "Painel do Barbeiro (Admin)":
    st.title("📊 Painel de Controle")

    if not acesso_admin_liberado:
        st.info("👈 Por favor, insira sua senha no menu lateral para visualizar os dados.")
    else:
        df = buscar_todos_dados_para_painel()

        if df.empty:
            st.warning("Nenhum agendamento encontrado no banco de dados.")
        else:
            data_filtro = st.date_input("Filtrar visualização para a data:", value=pegar_hora_local().date(), format="DD/MM/YYYY")
            data_filtro_str = data_filtro.strftime("%d/%m/%Y")
            
            df_dia = df[df['Data'] == data_filtro_str].copy()
            if not df_dia.empty:
                df_dia = df_dia.sort_values(by="Hora")
            
            # --- MÉTRICAS DE RESUMO ---
            col_res1, col_res2, col_res3 = st.columns(3)
            with col_res1:
                st.metric("Total de Clientes", len(df_dia))
            with col_res2:
                try:
                    faturamento = df_dia['Serviço'].apply(lambda x: int(re.findall(r'\d+', x)[0]) if re.findall(r'\d+', str(x)) else 0).sum()
                    st.metric("Faturamento Estimado", f"R$ {faturamento}")
                except:
                    st.metric("Faturamento Estimado", "R$ 0")
            with col_res3:
                agora_str = pegar_hora_local().strftime("%H:%M")
                if not df_dia.empty:
                    pendentes = df_dia[df_dia['Hora'] >= agora_str]
                    proximo = pendentes.iloc[0]['Nome'] if not pendentes.empty else "Finalizado"
                else:
                    proximo = "-"
                st.metric("Próximo da Fila", proximo)

            st.divider()
            
            # --- LISTAGEM DOS AGENDAMENTOS (Cards) ---
            st.subheader(f"📅 Agenda para {data_filtro_str}")
            
            if df_dia.empty:
                st.info("Você não tem clientes agendados para esta data.")
            else:
                for index, row in df_dia.iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
                        c1.subheader(f"{row['Hora']}")
                        c2.write(f"**Nome:** {row.get('Nome', 'Sem Nome')}")
                        c3.write(f"**Serviço:** {row.get('Serviço', '-')}")
                        
                        num = str(row.get('Telefone', ''))
                        limpo = re.sub(r'\D', '', num)
                        if limpo:
                            c4.link_button("📱 WhatsApp", f"https://wa.me/55{limpo}", use_container_width=True)
                        else:
                            c4.write("Sem telefone")

            st.divider()
            with st.expander("Ver Planilha Completa Bruta"):
                st.dataframe(df, use_container_width=True)
