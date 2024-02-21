import redis
import transcribe
transcript = transcribe.get_transcript("2534a64d-532e-449f-863a-a0980edf8574")
payload = transcript['utterances']

print(payload)