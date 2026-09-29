import os
from app.container_setup import ENV_PATH, write_env, write_posts
if not ENV_PATH.exists():
    write_env({'SITE_ID':'UNCONFIGURED','SITE_NAME':'Labrixwash','POST_ID':'POST-01','POST_NAME':'Post 1','LOCAL_REPORT_API_KEY':os.environ['REPORT_API_KEY'],'SITE_REPORT_API_KEY':os.environ['REPORT_API_KEY'],'REPOSITORY_MODE':'postgres','POSTGRES_DSN':os.environ['REPORT_POSTGRES_DSN'],'POSTS_CONFIG':'/data/posts.yaml','HUB_DATABASE_PATH':'/data/hub.sqlite3','WASH_ENGINE_URL':'http://wash-engine:8080','TELEGRAM_ENABLED':'false','TIMEZONE':'Asia/Tashkent'})
    write_posts('UNCONFIGURED','Labrixwash',[{'id':'POST-01','name':'Post 1','host':'127.0.0.1','port':8091,'api_key_env':'SITE_REPORT_API_KEY','enabled':True}])
os.execvp('supervisord',['supervisord','-c','/etc/supervisor.conf'])
