from concurrent.futures import ThreadPoolExecutor, as_completed
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
from ruamel.yaml import YAML

#Yaml
yaml = YAML()
yaml.preserve_quotes = True

#Globals
load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

APICOST = .002 # Depends on the model https://openai.com/pricing
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = 20
LOCK = threading.Lock()
WIDTH = 70
LISTWIDTH = 75
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
CODE102 = True
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False
CODE356 = False
CODE320 = False
CODE111 = False

def handleACE(filename, estimate):
    global ESTIMATE, TOKENS, TOTALTOKENS, TOTALCOST
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(['', TOKENS, None], end - start, filename))
        with LOCK:
            TOTALCOST += TOKENS * .001 * APICOST
            TOTALTOKENS += TOKENS
            TOKENS = 0

        return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')
    
    else:
        with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
            start = time.time()
            translatedData = openFiles(filename)

            # Print Result
            end = time.time()
            yaml.dump(translatedData[0], outFile)
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOTALCOST += translatedData[1] * .001 * APICOST
                TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='UTF-8') as f:
        data = yaml.load(f)

        # Map Files
        if 'Map' in filename and filename != 'MapInfos.yaml':
            translatedData = parseMap(data, filename)

        # CommonEvents Files
        elif 'CommonEvents' in filename:
            translatedData = parseCommonEvents(data, filename)

        # Actor File
        elif 'Actors' in filename:
            translatedData = parseNames(data, filename, 'Actors')

        # Armor File
        elif 'Armors' in filename:
            translatedData = parseNames(data, filename, 'Armors')

        # Weapons File
        elif 'Weapons' in filename:
            translatedData = parseNames(data, filename, 'Weapons')
        
        # Classes File
        elif 'Classes' in filename:
            translatedData = parseNames(data, filename, 'Classes')

        # Enemies File
        elif 'Enemies' in filename:
            translatedData = parseNames(data, filename, 'Enemies')

        # Items File
        elif 'Items' in filename:
            translatedData = parseThings(data, filename)

        # MapInfo File
        elif 'MapInfos' in filename:
            translatedData = parseNames(data, filename, 'MapInfos')

        # Skills File
        elif 'Skills' in filename:
            translatedData = parseSS(data, filename)

        # Troops File
        elif 'Troops' in filename:
            translatedData = parseTroops(data, filename)

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
    events = data['events']
    global LOCK

    # Translate displayName for Map files
    if 'Map' in filename:
        response = translateGPT(data['displayName'], 'Reply with only the english translated name', False)
        totalTokens += response[1]
        data['displayName'] = response[0].strip('.\"')

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event['pages']:
                totalLines += len(page['list'])
    
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    futures = [executor.submit(searchCodes, page, pbar) for page in event['pages'] if page is not None]
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
            totalLines += len(page['list'])

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

def parseTroops(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for troop in data:
        if troop is not None:
            for page in troop['pages']:
                totalLines += len(page['list']) + 1 # The +1 is because each page has a name.

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        for troop in data:
            if troop is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(searchCodes, page, pbar) for page in troop['pages'] if page is not None]
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

def parseThings(data, filename):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchThings(name, pbar)       
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
    for term in data['terms']:
        termList = data['terms'][term]
        totalLines += len(termList)
    totalLines += len(data['game_title'])
    totalLines += len(data['armor_types'])
    totalLines += len(data['skill_types'])
    totalLines += len(data['weapon_types'])
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            result = searchSystem(data, pbar)       
            totalTokens += result
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchThings(name, pbar):
    tokens = 0

    # Set the context of what we are translating
    responseList = []
    responseList.append(translateGPT(name['name'], 'Reply with only the english translated menu item name.', False))
    responseList.append(translateGPT(name['description'], 'Reply with only the english translated description.', True))
    # responseList.append(translateGPT(name['note'], 'Reply with only the english translated note.', False))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.\"')
    responseList[1] = textwrap.fill(responseList[1], LISTWIDTH)
    name['description'] = responseList[1].strip('\"')
    # name['note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchNames(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        newContext = 'Reply with only the english translation. The original text is a menu item.'
    if 'Armors' in context:
        newContext = 'Reply with only the english translation.'
    if 'Classes' in context:
        newContext = 'Reply with only the english translated class name'
    if 'MapInfos' in context:
        newContext = 'Reply with only the english translated map name'
    if 'Enemies' in context:
        newContext = 'Reply with only the english translated enemy'
    if 'Weapons' in context:
        newContext = 'Reply with only the english translated weapon name'

    # Extract Data
    responseList = []
    responseList.append(translateGPT(name['name'], newContext, True))
    if 'Actors' in context:
        responseList.append(translateGPT(name['profile'], '', True))

    if 'Armors' in context or 'Weapons' in context:
        responseList.append(translateGPT(name['description'], '', True))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.\"')
    if 'Actors' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        name['profile'] = translatedText.strip('\"')

    if 'Armors' in context or 'Weapons' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        name['description'] = translatedText.strip('\"')
    pbar.update(1)

    return tokens

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    speaker = ''
    match = []
    speakerCaught = False
    global LOCK

    # Regex
    subVarRegex = r'(\\+[a-zA-Z]+)\[([a-zA-Z0-9一-龠ぁ-ゔァ-ヴー\s]+)\]'
    reSubVarRegex = r'\<([\\a-zA-Z]+)([a-zA-Z0-9一-龠ぁ-ゔァ-ヴー\s]+)\>'

    try:
        for i in range(len(page['list'])):
            with LOCK:
                pbar.update(1)

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Use the flags to skip codes.

            ## Event Code: 401 Show Text
            if page['list'][i]['code'] == 401 and CODE401 == True:    
                jaString = page['list'][i]['parameters'][0]
                oldjaString = jaString
                jaString = jaString.replace('ﾞ', '')
                jaString = jaString.replace('。', '.')
                jaString = re.sub(r'([\u3000-\uffef])\1{1,}', r'\1', jaString)

                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)

                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    jaString = page['list'][i]['parameters'][0]
                    jaString = jaString.replace('ﾞ', '')
                    jaString = jaString.replace('。', '.')
                    jaString = re.sub(r'([\u3000-\uffef])\1{1,}', r'\1', jaString)
                    currentGroup.append(jaString)

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ' '.join(currentGroup)

                    # Check for speaker
                    if '\\nw' in finalJAString:
                        match = re.findall(r'([\\]+nw\[([a-zA-Z0-9一-龠ぁ-ゔァ-ヴー\s]+)\])', finalJAString)
                        if len(match) != 0:
                            response = translateGPT(match[0][1], 'Reply with only the english translated actor', False)
                            tokens += response[1]
                            speaker = response[0].strip('.')

                            finalJAString = re.sub(r'([\\]+nw\[[a-zA-Z0-9一-龠ぁ-ゔァ-ヴー\s]+\])', '', finalJAString)

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯【】（）「」a-zA-ZＡ-Ｚ０-９\\]+', finalJAString)
                    finalJAString = re.sub(r'^[^ぁ-んァ-ン一-龯【】（）「」a-zA-ZＡ-Ｚ０-９\\]+', '', finalJAString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    
                    # Sub Vars
                    finalJAString = re.sub(subVarRegex, r'<\1\2>', finalJAString)

                    # Remove any textwrap
                    finalJAString = re.sub(r'\n', ' ', finalJAString)

                    # Translate
                    if speaker != '':
                        response = translateGPT(finalJAString, 'Previously Translated Text for Context: ' + ' '.join(textHistory) \
                                                + '\n\n\n###\n\n\nCurrent Speaker: ' + speaker, True)
                    else:
                        response = translateGPT(finalJAString, 'Previous Translated Text for Context: ' + ' '.join(textHistory), True)
                    tokens += response[1]
                    translatedText = response[0]

                    # ReSub Vars
                    translatedText = re.sub(reSubVarRegex, r'\1[\2]', translatedText)

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    # rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
                    if speaker != '':
                        textHistory.append(speaker + ': ' + translatedText)
                    else:
                        textHistory.append('\"' + translatedText + '\"')

                    # Name Handling
                    if len(match) != 0:
                        name = '\\nw[' + speaker + ']'
                        if name not in translatedText:
                            translatedText = translatedText + '\\nw[' + speaker + ']'

                    # if speakerCaught == True:
                    #     translatedText = speakerRaw + ':\n' + translatedText
                    #     speakerCaught = False

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Resub start and end
                    translatedText = startString + translatedText

                    # Set Data
                    page['list'][i]['parameters'][0] = translatedText.replace('\"', '')
                    speaker = ''
                    match = []

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []              

            ## Event Code: 122 [Control Variables] [Optional]
            if page['list'][i]['code'] == 122 and CODE122 == True:    
                jaString = page['list'][i]['parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if re.search(r'[a-zA-Z0-9]+', jaString):
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'([\u3000-\uffef])\1{2,}', r'\1\1', jaString)

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                endString = re.search(r'[^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', jaString)
                jaString = re.sub(r'[^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Sub Vars
                jaString = re.sub(subVarRegex, r'<\1\2>', jaString)

                # Translate
                response = translateGPT(jaString, 'Reply with only the english translation', False)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n', '\\']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # ReSub Vars
                translatedText = re.sub(reSubVarRegex, r'\1[\2]', translatedText)

                # Set Data
                page['list'][i]['parameters'][4] = startString + translatedText + endString

        ## Event Code: 357 [Picture Text] [Optional]
            if page['list'][i]['code'] == 357 and CODE357 == True:    
                if 'text' in page['list'][i]['parameters'][3]:
                    jaString = page['list'][i]['parameters'][3]['text']
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
                    response = translateGPT(jaString, '', True)
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
                    page['list'][i]['parameters'][3]['text'] = startString + translatedText

        ## Event Code: 101 [Name] [Optional]
            if page['list'][i]['code'] == 101 and CODE101 == True:    
                jaString = page['list'][i]['parameters'][4]
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
                response = translateGPT(jaString, 'Reply with only the english translation. NEVER reply in anything other than English. I repeat, only reply with the english translation of the original text.', False)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                speaker = translatedText
                page['list'][i]['parameters'][4] = translatedText

            ## Event Code: 355 or 655 Scripts [Optional]
            if (page['list'][i]['code'] == 355 or page['list'][i]['code'] == 655) and CODE355655 == True:
                jaString = page['list'][i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if page['list'][i]['code'] == 355 and '.setName' not in jaString:
                    continue

                # Don't want to touch certain scripts
                if page['list'][i]['code'] == 655 and 'this.' in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                endString = re.search(r'[^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', jaString)
                jaString = re.sub(r'[^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with only the english translation.', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                page['list'][i]['parameters'][0] = startString + translatedText + endString

            ## Event Code: 356 D_TEXT
            if page['list'][i]['code'] == 356 and CODE356 == True:
                jaString = page['list'][i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'PSM_SHOW_POPUP' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯【】（）「」]+-1 ', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯【】（）「」]+-1 ', '', jaString)
                endString = re.search(r' [^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', jaString)
                jaString = re.sub(r' [^ぁ-んァ-ン一-龯\<\>【】 。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with only the English Translation.', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Cant have spaces?
                translatedText = translatedText.replace(' ', '　')

                # Set Data
                page['list'][i]['parameters'][0] = startString + translatedText + endString

            ### Event Code: 102 Show Choice
            if page['list'][i]['code'] == 102 and CODE102 == True:
                for choice in range(len(page['list'][i]['parameters'][0])):
                    jaString = page['list'][i]['parameters'][0][choice]
                    translatedText = translatedText.replace(' 。', '.')

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】（）Ａ-Ｚ０-９]+', jaString)
                    jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】（）Ａ-Ｚ０-９]+', '', jaString)
                    endString = re.search(r'[^ぁ-んァ-ン一-龯【】 。！？（）Ａ-Ｚ０-９]+$', jaString)
                    jaString = re.sub(r'[^ぁ-んァ-ン一-龯【】 。！？（）Ａ-Ｚ０-９]+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    response = translateGPT(jaString, 'Keep your reply prompt.', True)
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][0][choice] = startString + translatedText + endString

            ### Event Code: 111 Script
            if page['list'][i]['code'] == 111 and CODE111 == True:
                for j in range(len(page['list'][i]['parameters'])):
                    jaString = page['list'][i]['parameters'][j]

                    # Check if String
                    if type(jaString) != str:
                        continue

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                    jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                    endString = re.search(r'[^ぁ-んァ-ン一-龯【】 。！？]+$', jaString)
                    jaString = re.sub(r'[^ぁ-んァ-ン一-龯【】 。！？]+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    response = translateGPT(jaString, 'Reply with only the english translation.', True)
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][j] = startString + translatedText + endString

            ### Event Code: 320 Set Variable
            if page['list'][i]['code'] == 320 and CODE320 == True:
                jaString = page['list'][i]['parameters'][1]
                translatedText = translatedText.replace(' 。', '.')

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯【】a-zA-Z\\]+', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯【】a-zA-Z\\]+', '', jaString)
                endString = re.search(r'[^ぁ-んァ-ン一-龯【】 。！？]+$', jaString)
                jaString = re.sub(r'[^ぁ-んァ-ン一-龯【】 。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                response = translateGPT(jaString, 'Reply with only the english translation.', True)
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                tokens += response[1]
                page['list'][i]['parameters'][1] = startString + translatedText + endString

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + oldjaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        # Translate
        if speaker != '':
            response = translateGPT(finalJAString, 'Previous text for context: ' + ' '.join(textHistory) \
                                    + '\n\n\n###\n\n\nCurrent Speaker: ' + speaker, True)
        else:
            response = translateGPT(finalJAString, 'Previous text for context: ' + ' '.join(textHistory), True)
        tokens += response[1]
        translatedText = response[0]

        # ReSub Vars
        translatedText = re.sub(reSubVarRegex, r'\1[\2]', translatedText)

        # TextHistory is what we use to give GPT Context, so thats appended here.
        rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
        if speaker != '':
            textHistory.append(speaker + ': ' + rawTranslatedText)
        else:
            textHistory.append('\"' + rawTranslatedText + '\"')

        # Name Handling
        if len(match) != 0:
            name = '\\nw[' + speaker + ']'
            if name not in translatedText:
                translatedText = translatedText + '\\nw[' + speaker + ']'

        # if speakerCaught == True:
        #     translatedText = speakerRaw + ':\n' + translatedText
        #     speakerCaught = False

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Resub start and end
        translatedText = startString + translatedText

        # Set Data
        page['list'][i]['parameters'][0] = translatedText.replace('\"', '')
        speaker = ''
        match = []

        # Keep textHistory list at length maxHistory
        if len(textHistory) > maxHistory:
            textHistory.pop(0)
        currentGroup = []     

    return tokens

def searchSS(state, pbar):
    '''Searches skills and states yaml files'''
    tokens = 0
    responseList = [0] * 7

    responseList[0] = (translateGPT(state['message1'], 'Reply with the english translated Action being performed and no subject.', False))
    responseList[1] = (translateGPT(state['message2'], 'Reply with the english translated Action being performed and no subject.', False))
    responseList[2] = (translateGPT(state.get('message3', ''), 'Reply with the english translated Action being performed and no subject..', False))
    responseList[3] = (translateGPT(state.get('message4', ''), 'Reply with the english translated Action being performed and no subject..', False))
    responseList[4] = (translateGPT(state['name'], 'Reply with only the english translation', True))
    # responseList[5] = (translateGPT(state['note'], 'Reply with only the translated english note.', False))
    if 'description' in state:
        responseList[6] = (translateGPT(state['description'], 'Reply with the english translated description.', True))

    # Put all our translations in a list
    for i in range(len(responseList)):
        if responseList[i] != 0:
            tokens += responseList[i][1]
            responseList[i] = responseList[i][0].strip('.\"')
    
    # Set Data
    if responseList[0] != '':
        if responseList[0][0] != ' ':
            state['message1'] = ' ' + responseList[0][0].lower() + responseList[0][1:]
    state['message2'] = responseList[1]
    if responseList[2] != '':
        state['message3'] = responseList[2]
    if responseList[3] != '':
        state['message4'] = responseList[3]
    state['name'] = responseList[4].strip('.')
    # state['note'] = responseList[5]
    if responseList[6] != 0:
        responseList[6] = textwrap.fill(responseList[6], LISTWIDTH)
        state['description'] = responseList[6].strip('\"')


    pbar.update(1)
    return tokens

def searchSystem(data, pbar):
    tokens = 0
    context = 'Reply with only the english translated menu item.'

    # Title
    response = translateGPT(data['game_title'], context, True)
    tokens += response[1]
    data['game_title'] = response[0].strip('.')
    pbar.update(1)
    
    # Terms
    for term in data['terms']:
        if term != 'messages':
            termList = data['terms'][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None:
                    response = translateGPT(termList[i], context, True)
                    tokens += response[1]
                    termList[i] = response[0].strip('.\"')
                    pbar.update(1)

    # Armor Types
    for i in range(len(data['armor_types'])):
        response = translateGPT(data['armor_types'][i], 'Reply with only the english translated armor type', False)
        tokens += response[1]
        data['armor_types'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Skill Types
    for i in range(len(data['skill_types'])):
        response = translateGPT(data['skill_types'][i], 'Reply with only the english translation', False)
        tokens += response[1]
        data['skill_types'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Weapon Types
    for i in range(len(data['weapon_types'])):
        response = translateGPT(data['weapon_types'][i], 'Reply with only the english translated equipment type. No disclaimers.', False)
        tokens += response[1]
        data['weapon_types'][i] = response[0].strip('.\"')
        pbar.update(1)
        
    return tokens

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    with LOCK:
        # If ESTIMATE is True just count this as an execution and return.
        if ESTIMATE:
            global TOKENS
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo-0613")
            TOKENS += len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
            return (t, 0)
    
    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+', t):
        return(t, 0)

    """Translate text using GPT"""
    if fullPromptFlag:
        system = "###\n" + history + PROMPT 
    else:
        system = 'You are going to pretend to be Japanese visual novel translator, \
editor, and localizer. ' + history
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ],
        request_timeout=30,
    )

    # Make sure translation didn't wonk out
    mlen=len(response.choices[0].message.content)
    elnt=10*len(t)
    if len(response.choices[0].message.content) > 9 * len(t):
        return [t, response.usage.total_tokens]
    else:
        return [response.choices[0].message.content, response.usage.total_tokens]
    