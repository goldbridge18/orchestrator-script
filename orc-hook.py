import time
import json,requests,time
import pyjq
import datetime,re,subprocess
import urllib.request
import telnetlib

from collections import Counter

'''
解决以下问题：
1.orchestrator集成的consul-client只上报数据master的变更信息,对slave的信息不更新上报至consul
2.当slave节点 故障是I/o、sql线程为no使对应的haproxy并不下线已经为故障的slave节点
3、如果在读写分离的时候,在haproxy配置的读端口下.不希望master提供服务
4、当master发生切换后,如果旧的master节点宕机之后重启后,如果haproxy相对应的配置没有被更改,就master可能会被haproxy检测到并提供服务.
————————————————
版权声明：本文为CSDN博主「柔于似水」的原创文章，遵循CC 4.0 BY-SA版权协议，转载请附上原文出处链接及本声明。
原文链接：https://blog.csdn.net/q936889811/article/details/103633791

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

        # print("allNodeList ",self.getAliasOfAllNode(request_cmd))
        # print("downList ", self.getClusterDownNodes(request_cmd))
        # print("upList ", self.getClusterUpNodes(request_cmd))
        # print("masterList ", self.getMasterNodes(request_cmd))
        # print("behindMasterList ", self.getSecondsBehindMaster(request_cmd))

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

    def checkIpAndPort(self):

        try:
            telnetlib.Telnet(self.ORCIP, self.ORCPORT, timeout=2)
            print("代理IP有效！")
        except:
            print("代理IP无效！")

    def check3Times(self,list,retry_times):
        reslist = []
        res = Counter(list)
        for key, val in res.items():
            if val == retry_times:
                reslist.append(key)
        return reslist



class wechatAlert(object):
    def __init__(self):
        self.CROPID = 'ww6be7e447e62b0b8e'
        self.SECRET = 'Vcjmxvhs-4zkVSgF_La1Q6u0-oRmb-DRD567I_8iFHI'
        self.AGENTID = 1000002
        self.USERID = 'xxxxxx'

    def getAcessToken(self):
        GURL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={cropid}&corpsecret={secret}".format(
            cropid=self.CROPID, secret=self.SECRET)
        res = requests.get(url=GURL)
        token = pyjq.one(".access_token",json.loads(res.text))
        return  token
    def sendMessage(self,context = ''):
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}".format(token=self.getAcessToken())
        data = {
               "touser" : self.USERID,
               "toparty" : "2",
               "totag" : "TagID1 | TagID2",
               "msgtype" : "textcard",
               "agentid" : self.AGENTID,
               "textcard" : {
                        "title" : "orc报警",
                        "description" : "<div class=\"gray\">2016年9月26日</div> <div class=\"normal\">异常服务主机列表：{context}，上述主机在haproxy配置被修改。</div><div class=\"highlight\">请于登录相关实例查看报警原因</div>".format(context=context),
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

if __name__ == "__main__":
    ##orchestrator配置信息
    apiIp = "10.0.34.78"
    apiPort = 3000
    consulIpAndPort = "10.0.34.78:8500"
    delaytime = 10
    retryTimes = 2

    # 文件路径
    templateFile = "./haproxy.ctmpl"
    templateFile1 = "./haproxy.ctmpl.1"
    haproxyCfg = "/etc/haproxy/haproxy.cfg"
    logfile = "/var/log/orch_hook.log"

    # templateFile = "/etc/consul-template/templates/haproxy.ctmpl"
    # templateFile1 = "/etc/consul-template/templates/haproxy.ctmpl.1"
    # haproxyCfg = "/etc/haproxy/haproxy.cfg"
    # logfile = "/var/log/orch_hook.log"
    w = wechatAlert()
    orchook = OrcHook(apiIp, apiPort, delaytime)
    count = 0
    while True:
        flag = True
        starttime = datetime.datetime.now()

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

                    offlineNodeList = [val + "_"+ x for x in offlineNodeList]
                    onlineNodeList = [val + "_"+ x for x in onlineNodeList]

                    moveNodeList += offlineNodeList
                    addNodeList +=  onlineNodeList
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
        haproxyReloadCmd = "systemctl reload haproxy"
        #consul-template
        if flag == False:
            consulTemplateCmd = "/usr/local/bin/consul-template -consul-addr={consulIpAndPort}" \
                                " -template \"{templateFile}:{haproxycfg}\" " \
                                "-once".format(consulIpAndPort=consulIpAndPort ,templateFile=templateFile1,haproxycfg=haproxyCfg)
            consulOutCmd = subprocess.getstatusoutput(consulTemplateCmd)
            if consulOutCmd[0] != 0:
                subprocess.getstatusoutput(consulRestartCmd)

            #reload haproxy
            haproxyOutCmd = subprocess.getstatusoutput(haproxyReloadCmd)
            # print(haproxyOutCmd)
            if haproxyOutCmd[0] == 0 :
                    subprocess.getstatusoutput(consulRestartCmd)
            else:
                cmd = "/bin/cp -rf {templateFile1} {templateFile}".format(templateFile1=templateFile1,templateFile=templateFile)
                subprocess.getstatusoutput(cmd)
                print("---")
            w.sendMessage(tmpList)
            print("------>",tmpList)
        else:
            print("没有信息更改！")
        endtime = datetime.datetime.now()

        print("消耗总时间：",endtime-starttime)
        # exit()
        time.sleep(1)
