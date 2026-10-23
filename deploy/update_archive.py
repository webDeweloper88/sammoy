"""Portable Docker config identities for classic and containerd image stores."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile

def config_references(path, expected=None):
    with tarfile.open(path,'r:') as t:
        def read(name):
            p=t.getmember(name)
            if not p.isfile() or p.size>1024*1024:raise ValueError('invalid_image_archive')
            data=t.extractfile(p).read()
            if name.startswith('blobs/sha256/') and hashlib.sha256(data).hexdigest()!=name.rsplit('/',1)[-1]:raise ValueError('invalid_image_digest')
            return json.loads(data)
        manifest=read('manifest.json');refs={}
        for row in manifest:
            if row.get('RepoTags'):raise ValueError('mutable_tags_in_archive')
            digest=PurePosixPath(row['Config']).name.removesuffix('.json')
            if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid_image_digest')
            refs['sha256:'+digest]='sha256:'+digest
        if expected is not None and set(refs)!=set(expected):raise ValueError('image_set_mismatch')
        if 'index.json' in t.getnames():
            index=read('index.json')
            def walk(digest,root,depth=0):
                if depth>8:raise ValueError("invalid_image_index_depth")
                if not re.fullmatch('sha256:[a-f0-9]{64}',digest):raise ValueError('invalid_image_digest')
                obj=read('blobs/sha256/'+digest[7:])
                if 'config' in obj:
                    config=obj['config']['digest']
                    if config in refs:refs[config]=root
                else:
                    for item in obj.get('manifests',[]):walk(item['digest'],root,depth+1)
            for item in index.get('manifests',[]):
                if any(k in item.get('annotations',{}) for k in ('org.opencontainers.image.ref.name','io.containerd.image.name')):raise ValueError('mutable_tags_in_archive')
                walk(item['digest'],item['digest'])
        return refs
