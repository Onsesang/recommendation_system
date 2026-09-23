"""Resumable local orchestration, redacted stage notifications, bounded retry backoff."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request

from pipeline import ROOT,ART,write


def notify(message):
    endpoint=os.environ.get('DISCORD_WEBHOOK_URL')
    if not endpoint:return 'not_configured'
    for attempt in range(3):
        try:
            req=urllib.request.Request(endpoint,data=json.dumps({'content':message,'allowed_mentions':{'parse':[]}}).encode(),
                                       headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'},method='POST')
            with urllib.request.urlopen(req,timeout=15) as response:
                return f'HTTP_{response.status}'
        except Exception:
            if attempt<2:time.sleep(2**attempt)
    return 'delivery_failed_endpoint_redacted'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-pid',type=int);args=parser.parse_args()
    ART.mkdir(exist_ok=True);logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    lock=(ART/'runner.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.wait_pid:
        proc=f'/proc/{args.wait_pid}/cmdline'
        while os.path.exists(proc):
            with open(proc,'rb') as f:cmd=f.read().decode(errors='replace')
            if '19_explicit_preference_exploratory/pipeline.py' not in cmd:break
            write(ART/'runner_status.json',{'stage':'waiting_for_existing_checkpointed_inference','pid':args.wait_pid})
            time.sleep(30)
    stages=[('prepare',['pipeline.py','prepare']),('candidates',['evaluate.py','candidates']),
            ('infer',['pipeline.py','infer']),('repair1',['pipeline.py','repair']),('repair2',['pipeline.py','repair']),
            ('tests',['-m','unittest','-v','test_preference.py']),('evaluate',['evaluate.py','evaluate']),('report',['write_report.py'])]
    for name,args in stages:
        attempt=0
        while True:
            attempt+=1
            write(ART/'runner_status.json',{'stage':name,'attempt':attempt,'status':'running','time':time.time()})
            with (logs/f'{name}.log').open('a') as log:
                result=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode==0:
                delivery=notify(f'[촉감 추천 실험19] {name} 단계 완료. Human audit은 생략한 탐색 실험입니다.')
                with (ART/'notification_events.jsonl').open('a') as f:f.write(json.dumps({'stage':name,'delivery':delivery,'time':time.time()})+'\n')
                break
            notify(f'[촉감 추천 실험19] {name} 단계 실행 오류, 체크포인트에서 재시도합니다. attempt={attempt}')
            write(ART/'runner_status.json',{'stage':name,'attempt':attempt,'status':'retrying','exit_code':result.returncode})
            time.sleep(min(60,5*attempt))
    write(ART/'runner_status.json',{'status':'complete_exploratory_human_audit_skipped','time':time.time()})
    notify('[촉감 추천 실험19] 자동 추출·선호 프로필·추천 비교·검증·Notion/GPT 정리파일 생성이 완료됐습니다. 사람 검증 결과가 아닌 AI 기반 탐색 결과입니다.')


if __name__=='__main__':main()
