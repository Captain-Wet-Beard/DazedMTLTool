from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import threading
import time
import traceback
import tiktoken

from colorama import Fore
from dotenv import load_dotenv
import openai
from retry import retry
from tqdm import tqdm

#Globals
load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

APICOST = .002 # Depends on the model https://openai.com/pricing
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = 20
LOCK = threading.Lock()
WIDTH = 60
MAXHISTORY = 10
ESTIMATE = ''
TOTALCOST = 0
TOKENS = 0
TOTALTOKENS = 0

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

# Flags
CODE401 = True
CODE102 = False
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False

def handleACE(filename, estimate):
    global ESTIMATE, TOTALTOKENS, TOTALCOST, LOCK
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))

        with LOCK:
            TOTALCOST += translatedData[1] * .001 * APICOST
            TOTALTOKENS += translatedData[1]
    
    else:
        with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
            start = time.time()
            translatedData = openFiles(filename)

            # Print Result
            end = time.time()
            json.dump(translatedData[0], outFile, ensure_ascii=False)
            tqdm.write(getResultString(translatedData, end - start, filename))

        with LOCK:
            TOTALCOST += translatedData[1] * .001 * APICOST
            TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='UTF-8') as f:
        data = json.load(f)

        # Map Files
        if 'Map' in filename and filename != 'MapInfos.json':
            translatedData = parseMap(data, filename)

        # CommonEvents Files
        elif 'CommonEvents' in filename:
            translatedData = parseCommonEvents(data, filename)

        # Actor File
        elif 'Actors' in filename:
            translatedData = parseNames(data, filename, 'Actors')

        # Armors File
        elif 'Armors' in filename:
            translatedData = parseThings(data, filename, 'Armor')
        
        # Classes File
        elif 'Classes' in filename:
            translatedData = parseNames(data, filename, 'Classes')

        # Items File
        elif 'Items' in filename:
            translatedData = parseThings(data, filename, 'Items')

        # Enemies File

        # MapInfo File
        elif 'MapInfos' in filename:
            translatedData = parseNames(data, filename, 'MapInfos')

        # Skills File
        elif 'Skills' in filename:
            translatedData = parseSS(data, filename)

        # States File
        elif 'States' in filename:
            translatedData = parseSS(data, filename)

        # System File
        elif 'System' in filename:
            translatedData = parseSystem(data, filename)

        else:
            raise NameError(filename + ' Not Supported')
    
    return translatedData

def getResultString(translatedData, translationTime, filename):
    # File Print String
    tokenString = Fore.YELLOW + '[' + str(translatedData[1]) + \
        ' Tokens/${:,.4f}'.format(translatedData[1] * .001 * APICOST) + ']'
    timeString = Fore.BLUE + '[' + str(round(translationTime, 1)) + 's]'

    if translatedData[2] == None:
        # Success
        return filename + ': ' + tokenString + timeString + Fore.GREEN + u' \u2713 ' + Fore.RESET

    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            errorString = str(e) + Fore.RED
            return filename + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET

def parseMap(data, filename):
    totalTokens = 0
    totalLines = 0
    events = data['@events']
    global LOCK

    # Get total for progress bar
    for event in events.items():
        if event is not None:
            for item in event:
                if type(item) is dict:
                    for page in item['@pages']:
                        totalLines += len(page['@list'])
    
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events.items():
                if event is not None:
                    for item in event:
                        if type(item) is dict:
                            futures = [executor.submit(searchCodes, page, pbar) for page in item['@pages'] if page is not None]
                            for future in as_completed(futures):
                                try:
                                    totalTokens += future.result()
                                except Exception as e:
                                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseCommonEvents(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page['@list'])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokens += future.result()
                except Exception as e:
                    return [data, totalTokens, e]
    return [data, totalTokens, None]
    
def parseNames(data, filename, context):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchNames(name, pbar, context)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseThings(data, filename, context):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchThings(name, pbar, context)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSS(data, filename):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for ss in data:
                if ss is not None:
                    try:
                        result = searchSS(ss, pbar)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSystem(data, filename):
    totalTokens = 0
    totalLines = 0

    # Calculate Total Lines
    for term in data['@terms']:
        termList = data['@terms'][term]
        totalLines += len(termList)
    totalLines += len(data['@game_title'])
    totalLines += len(data['@terms']['@params'])
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            result = searchSystem(data, pbar)       
            totalTokens += result
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchThings(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    responseList = []
    responseList.append(translateGPT(name['@name'], 'Reply with only the menu item name.'))
    responseList.append(translateGPT(name['@description'], 'Reply with only the description.'))
    responseList.append(translateGPT(name['@note'], 'Reply with only the note.'))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['@name'] = responseList[0].strip('.')
    name['@description'] = responseList[1]
    name['@note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchNames(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        newContext = 'Reply with only the actor name'
    if 'Classes' in context:
        newContext = 'Reply with only the class name'
    if 'MapInfos' in context:
        newContext = 'Reply with only the map name'

    responseList = []
    responseList.append(translateGPT(name['@name'], newContext))

    if 'MapInfos' not in context:
        responseList.append(translateGPT(name['@description'], newContext))
        responseList.append(translateGPT(name['@note'], newContext))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['@name'] = responseList[0].strip('.')
    if 'MapInfos' not in context:
        name['@description'] = responseList[1]
        name['@note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    speaker = ''
    global LOCK

    try:
        for i in range(len(page['@list'])):
            with LOCK:
                pbar.update(1)

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Just comment out anything not needed.

            ## Event Code: 401 Show Text
            if page['@list'][i]['@code'] == 401 and CODE401 == True:    
                jaString = page['@list'][i]['@parameters'][0]

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'([\u3000-\uffef])\1{2,}', r'\1\1', jaString)
                   
                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)
                while (page['@list'][i+1]['@code'] == 401):
                    del page['@list'][i]  
                    jaString = page['@list'][i]['@parameters'][0]
                    jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)
                    currentGroup.append(jaString)

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ''.join(currentGroup)

                    # Improves translation but may break certain games
                    finalJAString = finalJAString.replace('\\n', '') 
                    finalJAString = finalJAString.replace('”', '')

                    # Sub Vars
                    finalJAString = re.sub(r'(\\+[a-zA-Z]+)\[([a-zA-Z0-9]+)\]', r'[\1|\2]', finalJAString)

                    # Translate
                    if speaker != '':
                        response = translateGPT(finalJAString, 'Previous text for context: ' + ' '.join(textHistory) + '\n\n\n###\n\n\nCurrent Speaker: ' + speaker)
                    else:
                        response = translateGPT(finalJAString, 'Previous text for context: ' + ' '.join(textHistory))
                    tokens += response[1]
                    translatedText = response[0]

                    # ReSub Vars
                    translatedText = re.sub(r'\[([\\a-zA-Z]+)\|([a-zA-Z0-9]+)]', r'\1[\2]', translatedText)

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    textHistory.append(speaker + ': ' + translatedText)

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    page['@list'][i]['@parameters'][0] = translatedText

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []

            ## Event Code: 122 [Control Variables] [Optional]
            if page['@list'][i]['@code'] == 122 and CODE122 == True:    
                jaString = page['@list'][i]['@parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'([\u3000-\uffef])\1{2,}', r'\1\1', jaString)

                # Sub Vars
                jaString = re.sub(r'\\+([a-zA-Z]+)\[([0-9]+)\]', r'[\1\2]', jaString)

                # Translate
                response = translateGPT(jaString, '')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n', '\\']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # ReSub Vars
                translatedText = re.sub(r'\[([a-zA-Z]+)([0-9]+)]', r'\\\\\1[\2]', translatedText)

                # Set Data
                page['@list'][i]['@parameters'][4] = '\"' + translatedText + '\"'

        ## Event Code: 357 [Picture Text] [Optional]
            if page['@list'][i]['@code'] == 357 and CODE357 == True:    
                if '@text' in page['@list'][i]['@parameters'][3]:
                    jaString = page['@list'][i]['@parameters'][3]['@text']
                    if type(jaString) != str:
                        continue
                    
                    # Definitely don't want to mess with files
                    if '_' in jaString:
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        continue

                    # Need to remove outside non-japanese text and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                    jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()

                    # Sub Vars
                    jaString = re.sub(r'\\+([a-zA-Z]+)\[([0-9]+)\]', r'[\1\2]', jaString)

                    # Translate
                    response = translateGPT(jaString, '')
                    tokens += response[1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['\"', '\\', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=50)

                    # ReSub Vars
                    translatedText = re.sub(r'\[([a-zA-Z]+)([0-9]+)]', r'\\\\\1[\2]', translatedText)

                    # Set Data
                    page['@list'][i]['@parameters'][3]['@text'] = startString + translatedText

        ## Event Code: 101 [Name] [Optional]
            if page['@list'][i]['@code'] == 101 and CODE101 == True:    
                jaString = page['@list'][i]['@parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    speaker = jaString
                    continue

                # Translate
                response = translateGPT(jaString, 'Reply with only the english translated name')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                speaker = translatedText
                page['@list'][i]['@parameters'][4] = translatedText

            ## Event Code: 355 or 655 Scripts [Optional]
            if (page['@list'][i]['@code'] == 355 or page['@list'][i]['@code'] == 655) and CODE355655 == True:
                jaString = page['@list'][i]['@parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if page['@list'][i]['@code'] == 355 and 'this.BLogAdd' not in jaString:
                    continue

                # Don't want to touch certain scripts
                if page['@list'][i]['@code'] == 655 and 'this.' in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                endString = re.search(r'[^ぁ-んァ-ン一-龯\<\>【】]+$', jaString)
                jaString = re.sub(r'[^ぁ-んァ-ン一-龯\<\>【】]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, '')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                page['@list'][i]['@parameters'][0] = startString + translatedText + endString

            ### Event Code: 102 Show Choice
            if page['@list'][i]['@code'] == 102 and CODE102 == True:
                for choice in range(len(page['@list'][i]['@parameters'][0])):
                    choiceText = page['@list'][i]['@parameters'][0][choice]
                    translatedText = translatedText.replace(' 。', '.')

                    # Need to remove outside non-japanese text and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', choiceText)
                    choiceText = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', choiceText)
                    if startString is None: startString = ''
                    else:  startString = startString.group()

                    if len(textHistory) > 0:
                        response = translateGPT(choiceText, 'Reply with the english translation for the answer. QUESTION: ' + textHistory[-1])
                    else:
                        response = translateGPT(choiceText, 'Reply with the english translation for the answer. QUESTION: ' + '')
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['@list'][i]['@parameters'][0][choice] = startString + translatedText

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + jaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        response = translateGPT(''.join(currentGroup), ' '.join(textHistory))
        tokens += response[1]
        translatedText = response[0]

        #Cleanup
        # TextHistory is what we use to give GPT Context, so thats appended here.
        textHistory.append(translatedText)

        # Textwrap
        if page['@list'][i]['@code'] == 401:
            translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Set Data
        page['@list'][i]['@parameters'][0] = translatedText

        # Keep textHistory list at length maxHistory
        if len(textHistory) > maxHistory:
            textHistory.pop(0)
        currentGroup = []
        page['@list'][i]['@parameters'][0] = translatedText
        currentGroup = []

    return tokens

def searchSS(state, pbar):
    '''Searches skills and states json files'''
    tokens = 0
    responseList = [0] * 6

    responseList[0] = (translateGPT(state['@message1'], 'Reply with only the message.'))
    responseList[1] = (translateGPT(state['@message2'], 'Reply with only the message.'))
    responseList[2] = (translateGPT(state.get('@message3', ''), 'Reply with only the message.'))
    responseList[3] = (translateGPT(state.get('@message4', ''), 'Reply with only the message.'))
    responseList[4] = (translateGPT(state['@name'], 'Reply with only the state name.'))
    responseList[5] = (translateGPT(state['@note'], 'Reply with only the note.'))

    # Put all our translations in a list
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]
    
    # Set Data
    state['@message1'] = responseList[0]
    state['@message2'] = responseList[1]
    if responseList[2] != '':
        state['@message3'] = responseList[2]
    if responseList[3] != '':
        state['@message4'] = responseList[3]
    state['@name'] = responseList[4].strip('.')
    state['@note'] = responseList[5]

    pbar.update(1)
    return tokens

def searchSystem(data, pbar):
    tokens = 0
    context = 'Reply with only the menu item.'

    # Title
    response = translateGPT(data['@game_title'], context)
    tokens += response[1]
    data['@game_title'] = response[0].strip('.')
    pbar.update(1)
    
    # Terms
    for term in data['@terms']:
        if term != '@messages':
            termList = data['@terms'][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None and 'json' not in term:
                    response = translateGPT(termList[i], context)
                    tokens += response[1]
                    termList[i] = response[0].strip('.\"')
                    pbar.update(1)
    
    return tokens

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history):
    with LOCK:
        # If ESTIMATE is True just count this as an execution and return.
        if ESTIMATE:
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
            tokens = len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
            return (t, tokens)
    
    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+', t):
        return(t, 0)

    """Translate text using GPT"""
    system = PROMPT + history 
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ],
        request_timeout=30,
    )

    return [response.choices[0].message.content, response.usage.total_tokens]