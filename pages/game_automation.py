import streamlit as st


def render():
    """Render the Game Automation page.

    Automation has been moved to the Test Case Generation page. Use the
    "Webhook response" panel on that page and the "Start Automation" button
    below it to run automation based on API responses.
    """
    st.header("Game Automation (moved)")
    st.write(
        "Automation UI has been moved to the Test Case Generation page.\n"
        "Open the Test Case Generation tab, submit a request to your webhook, and then"
        " use the 'Start Automation' button under the webhook response to run automation."
    )
    st.info("To avoid duplicate UIs, the automation controls now live on the first tab.")
