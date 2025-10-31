import streamlit as st

# keep page implementations in separate modules to avoid clutter
from pages.test_case_generation import render as page_test_case_generation
from pages.game_automation import render as page_game_automation
from pages.reports import render as page_reports


def main():
	st.set_page_config(page_title="Game Testing Dashboard", layout="wide")

	st.sidebar.title("Navigation")
	choice = st.sidebar.radio("Go to", [
		"Test Case Generation",
		"Game Automation",
		"Reports",
	])

	if choice == "Test Case Generation":
		page_test_case_generation()
	elif choice == "Game Automation":
		page_game_automation()
	elif choice == "Reports":
		page_reports()


if __name__ == "__main__":
	main()

