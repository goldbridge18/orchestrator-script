import time
import json,requests,time,os
import pyjq
import datetime,re,subprocess
import urllib.request
import telnetlib
import logging
from collections import Counter

'''
解决以下问题：
1.orchestrator集成的consul-client只上报数据master的变更信息,对slave的信息不更新上报至consul
2.当slave节点 故障是I/o、sql线程为no使对应的haproxy并不下线已经为故障的slave节点
3、如果在读写分离的时候,在haproxy配置的读端口下.不希望master提供服务
4、当master发生切换后,如果旧的master节点宕机之后重启后,如果haproxy相对应的配置没有被更改,旧master可能会被haproxy检测到并提供服务.
————————————————
版权声明：本文为CSDN博主「柔于似水」的原创文章，遵循CC 4.0 BY-SA版权协议，转载请附上原文出处链接及本声明。
原文链接：https://blog.csdn.net/q936889811/article/details/103633791

'''

'''
需要的安装的包
yum -y install python3.x86_64  python3-devel.x86_64  flex bison   libtool make automake  autoconf
pip3 install pyjq requests
'''
class OrcHook(object):
    def __init__(self,orc_ip,orc_port,num = 0):
        self.ORCIP = orc_ip
        self.ORCPORT = orc_port
        self.ORCAPI = "http://{orcip}:{orcport}/api".format(orcip=orc_ip,orcport=orc_port)
        self.NUM = num


    def getJsonData(self,condition,request_cmd):
        orc_url = "{api}{cmd}".format(api=self.ORCAPI,cmd=request_cmd)
        try:
            data = pyjq.all(condition, url=orc_url)

        except urllib.error.HTTPError as e:
            print(request_cmd)

        return data

    def getClusterDownNodes(self,request_cmd):
        condition = ".[] | select((.Slave_IO_Running==false or .Slave_SQL_Running==false) and .ReplicationDepth==1) .Key.Hostname"
        return self.getJsonData(condition,request_cmd)

    def getClusterUpNodes(self,request_cmd):
        condition = ".[] | select(.Slave_IO_Running==true and .Slave_SQL_Running==true and .ReplicationDepth==1) .Key.Hostname"
        return self.getJsonData(condition, request_cmd)

    def getMasterNodes(self,request_cmd):
        condition = ".[] | select(.ReplicationDepth==0) .Key.Hostname"
        return self.getJsonData(condition, request_cmd)

    def getDelayNodes(self,request_cmd):
        condition = ".[] | select(.Slave_IO_Running==true and .Slave_SQL_Running==true and .ReplicationDepth==1 " \
                    "and .SQLDelay > {delaytime}) .Key.Hostname".format(delaytime=self.NUM)
        return self.getJsonData(condition, request_cmd)

    def getSecondsBehindMaster(self,request_cmd):
        condition = ".[] | select(.ReplicationDepth==1 and .SecondsBehindMaster.Int64 > {NUM}) " \
                    ".Key.Hostname".format(NUM=self.NUM)
        return self.getJsonData(condition, request_cmd)

    def getAliasOfAllNode(self,request_cmd):
        condition = ".[] | .Key.Hostname"
        return self.getJsonData(condition, request_cmd)

    def getMoveOrUpClusterNode(self,request_cmd):
        '''

        :param request_cmd:
        :return: 返回一个tupe  (下线list，上线list)
        '''
        moveNodeList = []
        upNodeList = []
        getAllNodeList = self.getAliasOfAllNode(request_cmd)
        getDownList = self.getClusterDownNodes(request_cmd)
        getUpList =  self.getClusterUpNodes(request_cmd)
        getMasterList =  self.getMasterNodes(request_cmd)
        getBehindMasterList = self.getSecondsBehindMaster(request_cmd)

        if len(getBehindMasterList) != 0:
            for val in getBehindMasterList:
                moveNodeList.append(val)
                if val in getUpList:
                    getUpList.remove(val)

        if len(getDownList) !=0 :
            for val in getDownList:
                moveNodeList.append(val)

        if len(getUpList) != 0 :
            for val in getMasterList:
                moveNodeList.append(val)
            for val in getUpList:
                upNodeList.append(val)
        else:
            upNodeList.append(getMasterList[0])


        ###如果 所有的slave 都延迟高， 且状态up ，如果提供master服务？？？？？
        if len(moveNodeList) == len(getAllNodeList):
            moveNodeList.remove(getMasterList[0])
            return moveNodeList,getMasterList
        return moveNodeList,upNodeList

    def getClusterAlias(self):
        #curl  -sS http://${apiIpAndPort}/api/clusters-info | jq '.[] .ClusterAlias' -r
        reqAlias = "/clusters-info"
        condition = ".[] .ClusterAlias"
        return self.getJsonData(condition, reqAlias)

    def getCheckStatus(self,request_cmd):
        orc_url = "{api}{cmd}".format(api=self.ORCAPI, cmd=request_cmd)
        try:
            data = pyjq.all(".[]", url=orc_url)
            return True
        except urllib.error.HTTPError as e:
            # print(cmd,"不存在别名！")
            return False

    def sedConsulTemplate(self):
        pass

    def check3Times(self,list,retry_times):
        reslist = []
        res = Counter(list)
        for key, val in res.items():
            if val == retry_times:
                reslist.append(key)
        return reslist


class wechatAlert(object):
    def __init__(self):
        self.CROPID = 'ww6be7ex447e62xb0b8e'
        self.SECRET = 'Vcjmxvhs-4zkVSgF_La1Q6u0-oRxmb-DRD567I_8iFHI'
        self.AGENTID = 1000002
        self.USERID = 'xxxxx'

    def getAcessToken(self):
        GURL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={cropid}&corpsecret={secret}".format(
            cropid=self.CROPID, secret=self.SECRET)
        res = requests.get(url=GURL)
        token = pyjq.one(".access_token",json.loads(res.text))
        return  token
    def sendMessage(self,context = ''):
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}".format(token=self.getAcessToken())
        crunTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {
               "touser" : self.USERID,
               "toparty" : "2",
               "totag" : "TagID1 | TagID2",
               "msgtype" : "textcard",
               "agentid" : self.AGENTID,
               "textcard" : {
                        "title" : "orc报警",
                        "description" : "<div class=\"gray\">{crutime}</div> <div class=\"normal\">异常服务主机列表：{context}，上述主机在haproxy配置被修改。</div><div class=\"highlight\">请于登录相关实例查看报警原因</div>".format(crutime=crunTime,context=context),
                        "url" : "URL",
                                    "btntxt":"更多"
               },
               "enable_id_trans": 0,
               "enable_duplicate_check": 0,
               "duplicate_check_interval": 1800
        }

        message = (bytes(json.dumps(data),'utf8'))

        sendMessage = requests.post(url, message)
        print("微信报警：",sendMessage.text)

class LogServer(object):
    def logFile(self,context,modlename,logfilepath):
        curDate = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        # 创建logger记录器
        logger = logging.getLogger(modlename)
        logger.setLevel(logging.DEBUG)

        #日志保存到磁盘文件的处理器
        fh = logging.FileHandler(logfilepath,encoding='utf8')
        fh.setLevel(logging.DEBUG)

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        #sh.setFormatter(formatter)

        logger.addHandler(fh)
        #logger.addHandler(sh)
        if modlename == "info":
            logger.info(context)
        elif modlename == "debug":
            logger.debug(context)
        else:
            pass

        logger.removeHandler(fh)

class CommServer(object):
    def __init__(self):
        pass
    def checkIpAndPort(self,ipaddr_list,port):
        #判断ip 和端口是否可用
        # count = 0
        # while count < 4:
            for ip in ipaddr_list:
                try:
                    telnetlib.Telnet(ip, port, timeout=2)
                    # print("代理IP有效！",ip)
                    return ip
                except:
                    # print("代理IP无效！")
                    pass
                    # return None
            # count += 1

if __name__ == "__main__":
    ##orchestrator配置信息
    ipList = ["10.0.34.38","10.0.34.43","10.0.34.78"]
    apiPort = 3000
    delaytime = 100000000000000
    retryTimes = 2
    interval = 30   # 一次完整的执行时间是 需要考虑到 interval  retryTimes 检测ip可用的for循环 共同需要的时间的总和

    # 文件路径
    curDate = datetime.datetime.now().strftime("%Y-%m-%d")
    logfile = "orch_hook_{curtime}.log".format(curtime=curDate)

    templateFileBack = "/Users/eeo-dba001/PycharmProjects/pythonProject/back/haproxy.ctmpl"
    templateFile = "./haproxy.ctmpl"       #原模板文件
    templateFile1 = "./haproxy.ctmpl.1"   #生成新的模板文件
    #haproxyCfg = "/etc/haproxy/haproxy.cfg"

    # templateFileBack = "/etc/consul-template/back/haproxy.ctmpl"
    # templateFile = "/etc/consul-template/templates/haproxy.ctmpl"
    # templateFile1 = "/etc/consul-template/templates/haproxy.ctmpl.1"
    # haproxyCfg = "/etc/haproxy/haproxy.cfg"

    w = wechatAlert()
    log = LogServer()
    comm = CommServer()
    # orchook = OrcHook(apiIp, apiPort, delaytime)

    while True:
        flag = True
        starttime = datetime.datetime.now()

        #找到可用的ip
        # for apiIp in ipList:
        apiIp = comm.checkIpAndPort(ipList,apiPort)
        if apiIp == None:
            log.logFile("orc没有可用的ip和端口！！","info",logfile)
            w.sendMessage("orc没有可用的ip和端口！！")
            exit()
        orchook = OrcHook(apiIp, apiPort, delaytime)

        aliasList = orchook.getClusterAlias()

        moveNodeList = []
        addNodeList = []
        tmpList = []
        offlineNodeList = []
        onlineNodeList = []

        for i in range(retryTimes):
            for val in aliasList:
                cmd = "/cluster/alias/{alias}".format(alias=val)
                status = orchook.getCheckStatus(cmd)
                if status == True:
                    offlineNodeList = orchook.getMoveOrUpClusterNode(cmd)[0]
                    onlineNodeList = orchook.getMoveOrUpClusterNode(cmd)[1]
                    #生成 haproxy文件中对应的server名称： 别名_主机名
                    offlineNodeList = [val + "_"+ x for x in offlineNodeList]
                    onlineNodeList = [val + "_"+ x for x in onlineNodeList]

                    moveNodeList += offlineNodeList
                    addNodeList +=  onlineNodeList
            time.sleep(interval)  #连续获取api的值的间隔时间
        # 由于网络抖动或者其他原因，连续获取的api值可能不同，解决如下：
        #根据retryTimes=2 的值，来决定连续获取2次的值，对比2次的值都相等，说明连续获取api的值没有误判，，，调用函数  check3Times
        moveNodeList = orchook.check3Times(moveNodeList,retryTimes)
        addNodeList = orchook.check3Times(addNodeList,retryTimes)

        with open(templateFile,"r") as f1,open(templateFile1,"w",encoding= 'utf8') as f2:
            for val in f1.readlines():
                for val01 in addNodeList:
                    if val01 in val:
                        if re.search('weight \d+', val).group() != "weight 10":
                            flag = False
                            tmpList.append('{val01}:up'.format(val01=val01))
                        val = re.sub('weight \d+',"weight 10",val)

                for val01 in moveNodeList:
                    if val01 in val:
                        if re.search('weight \d+', val).group() != "weight 0":
                            flag = False
                            tmpList.append('{val01}:down'.format(val01=val01))
                        val = re.sub('weight \d+',"weight 0",val)

                f2.write(val)

        consulRestartCmd = "systemctl restart consul-template"
        # haproxyReloadCmd = "systemctl reload haproxy"
        #consul-template
        if flag == False:
            # consulTemplateCmd = "/usr/local/bin/consul-template -consul-addr={consulIpAndPort}" \
            #                     " -template \"{templateFile}:{haproxycfg}\" " \
            #                     "-once".format(consulIpAndPort=consulIpAndPort ,templateFile=templateFile1,haproxycfg=haproxyCfg)
            backTempaleFile = "/bin/cp -rf {templateFile} {backpath}-{curtime}".format(templateFile=templateFile,backpath=templateFileBack,curtime=datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
            # if not os.path.exists("/etc/consul-template/back/"):
            #     os.makedirs("/etc/consul-template/back/")

            replaceFileCmd = "/bin/cp -rf {templateFile1} {templateFile}".format(templateFile1=templateFile1,
                                                                      templateFile=templateFile)
            print(subprocess.getstatusoutput(backTempaleFile))
            subprocess.getstatusoutput(replaceFileCmd)
            consulOutCmd = subprocess.getstatusoutput(consulRestartCmd)
            if consulOutCmd[0] != 0:
                log.logFile(consulOutCmd,"debug",logfile)
                w.sendMessage("consul-template 重启失败！！！")
            else:
                log.logFile("consul-template restart successful", "debug", logfile)

            w.sendMessage(tmpList)
            log.logFile("发生更改的节点：{a}".format(a = tmpList), "info", logfile)
            print("------>",tmpList)
        else:
            print("没有信息更改！")
            log.logFile("没有信息更改","",logfile)
        endtime = datetime.datetime.now()

        print("消耗总时间：",endtime-starttime)
