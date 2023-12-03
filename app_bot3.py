import streamlit as st
import asyncio
import os
import requests
import json
import openai
from autogen.agentchat.contrib.retrieve_user_proxy_agent import RetrieveUserProxyAgent
import autogen
import re
from chromadb.utils import embedding_functions
import chromadb


st.set_page_config(layout="wide")

st.write("""# Technician's Mate: Work Order Adviser Bot """)

tab1, tab2 = st.tabs(["Show Main Conversations", "Show All Conversations"])

class TrackGroupChatManager(autogen.GroupChatManager):
	def _process_received_message(self, message, sender, silent):

		with tab1:
			if ( ('UserProxyAgent' in str(sender)) & ~(('exitcode' in str(message)) or ('retrieve_content' in str(message)))  ):            
				with st.chat_message('Technician', avatar="👨🏻‍💼"):
					st.markdown(''' :blue[{}]'''.format(message))
       
			elif( ('AssistantAgent' in str(sender)) &   ~( ('retrieve_content' in str(message)) or ('WO_Nov_bot3.csv' in str(message))) ):
				with st.chat_message('Assistant', avatar="🤖"):
					st.markdown(':green[{}]'.format(re.sub(r'\[.*?\]', '', message)) )
        
		with tab2:
			if ( 'UserProxyAgent' in str(sender) ):            
				with st.chat_message('Technician', avatar="👨🏻‍💼"):
					st.markdown(''' :blue[{}]'''.format(message))
            
			elif( ('AssistantAgent' in str(sender)) & ~('retrieve_content' in str(message)))  :
				with st.chat_message('Assistant', avatar="🤖"):
					st.markdown(':green[{}]'.format(re.sub(r'\[.*?\]', '', message)) )

		return super()._process_received_message(message, sender, silent)

selected_model = None
selected_key = 'sk'

st.markdown("""
<style>
    [data-testid=stSidebar] {
        background-color: #90EE90;
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("LLM Model Selection")
    selected_model = st.selectbox("Model", ['gpt-3.5-turbo', 'gpt-4-32k'], index=1)
    #uploaded_file = st.file_uploader("Choose an Image ...", type="jpg")

config_list = [
    {
        'model': selected_model,
        'api_key': 'f84978cd0c4f4006beabfbc6aadf8c06',
        "base_url": "https://cog-keslq7urc6ly4.openai.azure.com/",
        "api_type": "azure",
        "api_version": "2023-07-01-preview"
    }
]


user_input = st.chat_input("Hi Technician, please provide your request....")  

with st.container():

	if user_input:
		if not selected_key or not selected_model:
			st.warning('You must provide valid Azure OpenAI API credentials and choose preferred model', icon="⚠️")
			st.stop()
        
		llm_config = {
		        "functions": [
		            {
		                "name": "retrieve_content",
		                "description": "retrieve content for question answering.",
		                "parameters": {
		                    "type": "object",
		                    "properties": {
		                        "message": {
		                            "type": "string",
		                            "description": "Refined message which keeps the original meaning and can be used to retrieve content for code generation and question answering.",
		                        }
		                    },
		                    "required": ["message"],
		                },
		            },
		        ],
		        "config_list": config_list,
		        "timeout": 60,
		        "cache_seed": 42,
		}

		llm_config1 = {
		        "config_list": config_list,
		        "temperature": 0,
		}


		termination_msg = (lambda x: isinstance(x, dict) and "TERMINATE" == str(x.get("content", ""))[-9:].upper()) or (lambda x: x.get("content", "").rstrip().endswith("TERMINATE")) or x.get("content", "").strip() == ""

		technician = autogen.UserProxyAgent(
		    name="technician",
		    is_termination_msg=termination_msg,
		    human_input_mode="NEVER",
		    max_consecutive_auto_reply = 5,
		    system_message='''The technician who ask questions and give tasks. Reply `TERMINATE` if the task is done.''',
		    llm_config=llm_config1,  # we don't want to execute code in this case.
		    code_execution_config={"last_n_messages": 3, "work_dir": "groupchat_bot3", "use_docker": False},
		    default_auto_reply="Reply `TERMINATE` if the task is done.",
		)

		rag_assistant = RetrieveUserProxyAgent(
		    name="rag_assistant",
		    is_termination_msg=termination_msg,
		    system_message="Assistant who has extra content retrieval power for solving difficult problems.",
		    human_input_mode="NEVER",
		    max_consecutive_auto_reply=3,
		    retrieve_config={
		        "task": "qa",
		        "docs_path": "Facility Maintenance Handbook 2023.pdf",
		        "chunk_token_size": 1000,
		        "model": config_list[0]["model"],
		        "client": chromadb.PersistentClient(path="/tmp/chromadb"),
		        "collection_name": "groupchatA",
		        "get_or_create": True,
		    },
		    code_execution_config=False,  # we don't want to execute code in this case.
		)

		planner = autogen.AssistantAgent(
		    name="planner",
		    is_termination_msg=termination_msg,
		    system_message='''You are a python engineer. suggest code to python related questions asked by the technician. 
		    
		    You have two distinctive tasks:

		        if the technician asks about explaining how to resolve an asset maintenance issue such as 'how to resolve roof leakage'? then proceed to Task 1 and you will never work on Task 2.
		        else if if the technician asks about any new workorder that is not yet started? then proceed to Task 2 and you will never work on Task 1.
		        
		            Task 1: to answer the question asked by technician using 'retrieve_content' function calling. 

		        if the technician asks about explaining how to resolve an asset maintenance issue such as 'how to resolve roof leakage'? then proceed to Task 1 and you will never work on Task 2.
		        else if if the technician asks about any new workorder that is not yet started? then proceed to Task 2 and you will never work on Task 1.
		        
		            Taks 2: requires suggesting python code to determine from the 'WO_Nov_bot3.csv' database which work order have the 'not yet started' value in the 'status' column, and based on this condition, extract the 'assetName', 'assetBuildingFloorLocation', 'assetSkills', 'subject', and 'createdDate' details these rows
		            The is a database that contains the Historical and new work orders in the 'WO_Nov_bot3.csv'. Treat 'WO_Nov_bot3.csv' as a database. 
		                The 'WO_Nov_bot3.csv' work order database has the latest historical and new work order issues. Treat the data in this CSV file as our database, and make sure you import the required Python libraries such as Pandas, fuzzywuzzy, and datetime.
		                Make sure you import the neccessary libraries in the begining of the code block, please provide workable code without using comment blocks.
		                
		                The 'WO_Nov_bot3.csv' work order database has the following columns and their definitions:
		                - assetName: name of the asset in terms of asset type
		                - assetSkills: required skill to maintain each asset
		                - assetFloor: floor location of assets
		                - assetBuildingFloorLocation: detailed location of assets
		                - workOrderNumber: it's an incremental number in the CSV file
		                - subject: maintenance issue that needs resolution
		                - status: current status of resolution; it's either resolved, ongoing, or not yet started
		                - actualStartDateTime: actual start date of resolution; if the job status is not yet started, keep the value empty
		                - workOrderPrimaryAgentName: Technician assigned to the job
		                - createdDate: the job created date and time; when converting the data type of createdDate, please use .strftime('%Y-%m-%d')
		                - createdBy: the requester's name
		                - totalWorkTime: if a job's status is resolved, this is the duration of maintenance work in minutes
		                - resolutionType: resolution status
		                - resolvedDate: resolution date
		                - satisfactionRating: rating from the requester
		                - resolutionNotes: remarks from the maintenance work order
		        
		        		Your only task is to suggest complete python code for extracting all rows from the database where the 'status' values are 'not yet started', extract the 'assetName', 'assetBuildingFloorLocation', 'assetSkills', 'subject', 'workOrderPrimaryAgentName', and 'createdDate' values and share it with the helpdesk. technician will execute the code. 

		        		When extracting the 'assetName', 'assetBuildingFloorLocation', 'assetSkills', 'subject', 'workOrderPrimaryAgentName', and 'createdDate' values, print out each column values one by one. 

		                helpdesk will review your code, and technician will execute your code. You are not needed to execute the code. 

		    ''', 
		    
		    llm_config=llm_config,
		)

		helpdesk = autogen.AssistantAgent(
		    name="helpdesk",
		    is_termination_msg=termination_msg,
		    system_message='''You are a code and results reviewer. Review code suggested by planner. Make sure planner suggests code, and technician executed the suggested code. 

		                    You will review the answers from technician's execution of the suggested code, and give a comment about it without mentioning the technician or planner, please do not comment about code quality to technician. 

		                    When the code has successfully answer the question or problem, please reply the answer to the technician in layman manner without mentioning about the code or code execution.
		    
		                    For Task 2, please share the 'assetName', 'assetBuildingFloorLocation', 'assetSkills', 'subject', 'workOrderPrimaryAgentName' and 'createdDate' details with the technician. With stronger emphasis on 'subject', 'createdDate', and 'workOrderPrimaryAgentName'. 

		                    Reply `TERMINATE` in the end when either task is completed''',
		    llm_config=llm_config,
		)

		def retrieve_content(message, n_results=5):
		    rag_assistant.n_results = n_results  # Set the number of results to be retrieved.
		    # Check if we need to update the context.
		    update_context_case1, update_context_case2 = rag_assistant._check_update_context(message)
		    if (update_context_case1 or update_context_case2) and rag_assistant.update_context:
		        rag_assistant.problem = message if not hasattr(rag_assistant, "problem") else rag_assistant.problem
		        _, ret_msg = rag_assistant._generate_retrieve_user_reply(message)
		    else:
		        ret_msg = rag_assistant.generate_init_message(message, n_results=n_results)
		    return ret_msg if ret_msg else message

		rag_assistant.human_input_mode = "NEVER"


		def _reset_agents():
		    technician.reset()
		    rag_assistant.reset()
		    planner.reset()
		    helpdesk.reset()

		_reset_agents()

		for agent in [planner, helpdesk]:
		    # update llm_config for assistant agents.
		    agent.llm_config.update(llm_config)

		for agent in [technician, planner, helpdesk]:
		    # register functions for all agents.
		    agent.register_function(
		        function_map={
		            "retrieve_content": retrieve_content,
		        }
		    )

		groupchat = autogen.GroupChat(agents=[technician, planner, helpdesk], messages=[], max_round=12)
		manager = TrackGroupChatManager(groupchat=groupchat, llm_config=llm_config)

		# Create an event loop
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)

        # Define an asynchronous function
		async def initiate_chat():
			await technician.a_initiate_chat(
				manager,
				message=user_input,
			)

        # Run the asynchronous function within the event loop
        #asyncio.run(initiate_chat())
		loop.run_until_complete(initiate_chat())
