import boto3
from botocore.exceptions import BotoCoreError, ClientError

import os
from contextlib import closing
from tempfile import gettempdir

import uuid
import logging

def _text2ssml(text, engine, pitch, rate, volume):
    if engine == "neural":
        # neural voices not support pitch tags
        return '<speak><prosody rate="{1}%" volume="{2}dB">{3}</prosody></speak>'.format(pitch, rate, volume, text)
    
    return '<speak><prosody pitch="{0}%" rate="{1}%" volume="{2}dB">{3}</prosody></speak>'.format(pitch, rate, volume, text)

def _synthesize(filename, text, lang_code, voice, engine, pitch, rate, volume):
    polly = boto3.client('polly')

    # Transform text into audio
    try:
        response = polly.synthesize_speech(
            OutputFormat='mp3',
            Text=_text2ssml(text, engine, pitch, rate, volume),
            TextType='ssml',
            LanguageCode=lang_code,
            VoiceId=voice,
            Engine=engine
        )
    except (BotoCoreError, ClientError) as e:
        logging.error(e)
        return 0

    # Save the audio stream returned by Amazon Polly on Lambda's temp 
    # directory.
    if "AudioStream" in response:
        with closing(response["AudioStream"]) as stream:
            with open(os.path.join(gettempdir(), filename), 'wb') as file:
                file.write(stream.read())

    return int(response["RequestCharacters"])

def _upload(filename):
    # upload to s3
    s3 = boto3.client('s3')

    try:
        s3.upload_file(os.path.join(gettempdir(), filename), os.environ['audioBucket'], filename)
        s3.put_object_acl(ACL='public-read', Bucket=os.environ['audioBucket'], Key=filename)
    except ClientError as e:
        logging.error(e)
        return ""

    region = os.environ['region']
    
    if region is None:
        url_begining = "https://s3.amazonaws.com/"
    else:
        url_begining = "https://s3-" + str(region) + ".amazonaws.com/"
    
    voice_url = url_begining \
            + str(os.environ['audioBucket']) \
            + "/" \
            + filename
    
    return voice_url

def _synthesize_task(text, lang_code, voice, engine, pitch, rate, volume):
    polly = boto3.client('polly')

    # Transform text into audio with task
    try:
        response = polly.start_speech_synthesis_task(
            OutputS3BucketName=os.environ['audioBucket'],
            OutputFormat='mp3',
            Text=_text2ssml(text, engine, pitch, rate, volume),
            TextType='ssml',
            LanguageCode=lang_code,
            VoiceId=voice,
            Engine=engine
        )

        return response["SynthesisTask"]["TaskId"]
    except (BotoCoreError, ClientError) as e:
        logging.error(e)
        return ""

def synthesize(event, context):
    # request params
    try:
        pitch = event["pitch"]
        rate = event["speakingRate"]
        volume = event["volumeGainDb"]
        voice = event["voiceId"]
        lang_code = event["langCode"]
        engine = event["engine"]
        content = event["content"]
        content_type = event["contentType"]
    except Exception as e:
        logging.error(e)
        return None, 500

    # response placeholder
    voice_url = ""
    request_chars = 0
    task_id = ""

    if len(content) <= 3000:
        # generate unique filename
        filename = "{0}.mp3".format(str(uuid.uuid4()))
        # synthezie speech
        request_chars = _synthesize(filename, content, lang_code, voice, engine, pitch, rate, volume)
        if request_chars > 0:
            # no error, upload to s3 bucket
            voice_url = _upload(filename)
    else:
        task_id = _synthesize_task(content, lang_code, voice, engine, pitch, rate, volume)
    
    response = {
        "voiceUrl": voice_url,
        "requestChararacters": request_chars,
        "taskId": task_id
    }

    return response