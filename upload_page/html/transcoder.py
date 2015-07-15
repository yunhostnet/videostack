#!/usr/bin/env python
import hashlib
import configparser
import os
import sys
import re
import select
import subprocess
import io
import time
import redis
import signal
import shutil
from logging import warning, info, debug
from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK

class Transcoder:
    def __init__(self):
        self.config = self.read_conf()
        #signal.signal(signal.SIGCHLD, self.child_pid_reap())

    def handle_body(self, name, body):
        if name == b'video_id':
            uuid = body.decode().rstrip()
            self.uuid = "b1946ac92492d2347c6235b4d2611184"
            self.segment_list_name = 'x100_list_' + uuid + '_' + '400'
            self.init_popen_handler()
        elif(name == b'upload'):
            self.run_cmd_async(body)

    def read_conf(self):
        configfile = 'conf/transcoder.conf'
        if not os.path.exists(configfile):
            print("no config file")
            sys.exit(1)
        config = configparser.ConfigParser()
        config.read(configfile)

        return config

    def _md5(self, filename):
        m = hashlib.md5()
        m.update(filename.encode())
        md5_str = m.hexdigest()
        return md5_str

    def target_file(self, filename, file_type):
        #config = self.read_conf()
        basedir = self.config['storage']['release_dir']
        md5_str = self._md5(filename)

        dir1 = md5_str[:3]
        dir2 = md5_str[3:6]
        dir3 = md5_str[6:9]

        target_dir   = basedir + '/' + file_type + '/' + dir1 + '/' + dir2 + '/' + dir3
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        target_filename = target_dir + '/' + filename
        request_path_file = '/' + dir1 + '/' + dir2 + '/' + dir3 + '/' + filename

        return (target_filename, request_path_file)

    def init_write_handler(self,video_id):
        print(time.time())
        target_filename = self.target_filename(video_id)
        f = open(target_filename, mode='ab')
        self.write_handler = f
        return

    def init_popen_handler(self):
        cmd = self.build_cmd()
        print(cmd)
        p = subprocess.Popen(cmd, bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
        self.stdout = p.stdout
        self.stdin  = p.stdin
        flags = fcntl(self.stdout, F_GETFL)
        fcntl(self.stdout, F_SETFL, flags | O_NONBLOCK)
        return

    def run_cmd_async(self, body):
        self.stdin.write(body)
        while True:
            line = self.stdout.read(-1)
            #segment:'/tmp/a_sd_000030.flv' count:30 endedp=24 drop=0
            if line is None:
                break
            line = line.decode()
            ts_re = re.search("segment:\'(.*?)\'\s+count:(\d+).*", line)
            if ts_re:
                ts_file = ts_re.group(1)
                ts_filename = ts_file.split('/')[-1]
                file_index = ts_re.group(2)
                (target_file, request_file) = self.target_file(ts_filename,'ts')
                shutil.move(ts_file, target_file)
                create_time = self.file_create_time(target_file)
                filesize = self.file_size(target_file)
                video_info = self.uuid + '|' + self.config['base']['hostname'] + '|' + request_file + '|' + create_time + '|' \
                    + self.config['segment']['fps'] + '|' + self.config['segment']['fps_count'] + file_index
                #callback_api()
                print(video_info)

            snap_re = re.search("snap:\'(.*?)\'\s+count:(\d+).*", line)
            if snap_re:
                snap_img_file = snap_re.group(1)
                snap_index = snap_re.group(2)
                snap_img_filename = snap_img_file.split('/')[-1]
                (target_file, request_file) = self.target_file(snap_img_filename, 'snap')
                #print(target_file)
                shutil.move(snap_img_file, target_file)
                print("snap info path %s count %s" % (target_file, snap_index))
                #callback_api()
        return

    def file_create_time(self, afile):
        if not os.path.exists(afile):
            print("file %s not exist" % afile)
            sys.exit(1)
        return str(int(os.path.getctime(afile)))

    def file_size(self, afile):
        if not os.path.exists(afile):
            print("file %s not exist" % afile)
            sys.exit(1)
        statinfo = os.stat(afile)
        return statinfo.st_size

    def build_cmd(self):
        #target_ts_name, target_snap_name = self.target_filename()
        storage_dir = self.config['storage']['dir']
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)

        target_ts_name = storage_dir + '/' + self.uuid + "_%06d.flv"
        target_snap_name = storage_dir + '/' + self.uuid + "_%06d.jpg"
        cmd = ""
        cmd += "ffmpeg -v verbose -i - -map 0 -dn"
        cmd += " -c:v libx264 -profile:v main -b:v " + self.config['segment']['vbitrate'] + " -preset fast -s 86x48 "
        cmd += " -pix_fmt yuv420p"
        cmd += " -c:a libfaac -b:a " + self.config['segment']['abitrate'] + " -ar 32000 -ac 2"
        cmd += " -f segment -segment_format flv -segment_time 8"
        cmd += " -y " + target_ts_name
        cmd += " -r 1 -s 86x48 -y " + target_snap_name + " 2>&1"
        if cmd is not None:
            self.cmd = cmd
        else:
            self.cmd = ""
        return cmd

    def redis_conn(self):
        r = redis.StrictRedis(host=self.config['redis']['ip'], port=self.config['redis']['port'], db=0)
        return r

    def insert_redis(self, score, member):
        r = self.redis_conn()
        zz_key = self.segment_list_name
        print(self.segment_list_name)
        print(member)
        r.zadd(zz_key, score, member)
        r.expire(zz_key, self.config['segment']['expire'])
        info("insert redis ok")
        return 1

    def remove_redis(self, zz_key, member):
        r = self.redis_conn()
        zz_key = self.segment_list_name
        r.zrem(zz_key, member)
        info("delete redis ok")
        return 1

    #def child_pid_reap(self):
    #    result = 0
    #    while True:
    #        try:
    #            result = os.waitpid(-1, os.WNOHANG)
    #        except:
    #            warning("waitpid error")
    #        print("repead child process %d" % result[0])
    #    signal.signal(signal.SIGCHLD, self.child_pid_reap())

    #def fork_redis(self, segment_count, segment_info):
    #    pid = os.fork()
    #    if pid == 0:
    #        if self.insert_redis(segment_count, segment_info):
    #            sys.exit(0)
    #    return

    def __del__(self):
        self.stdin.close()
        while True:
            content = self.stdout.read(-1)
            if not content:
                break
            print(content)
        return
