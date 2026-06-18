import matplotlib.pyplot as plt
import seaborn as sns
import streamlit as st

# no st.set_page_config() here – only on main python file

# Show figures
def show(fig):
    if isinstance(fig, go.Figure):
        st.plotly_chart(fig, width='stretch')
    else:
        st.pyplot(fig)
        plt.close(fig)

# Run query from session state. run query defined in main page
run_query = st.session_state.get("run_query")

st.title("Dashboard")
