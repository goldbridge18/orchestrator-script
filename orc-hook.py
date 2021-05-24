import time

import pyjq
import datetime,re,subprocess
import urllib.request

class OrcHook(object):
    def __init__(self,orc_ip,orc_port,num = 0):

        self.orc_api = "http://{orcip}:{orcport}/api".format(orcip=orc_ip,orcport=orc_port)
        self.num = num

    def getJsonData(self,condition,request_cmd):
        orc_url = "{api}{cmd}".format(api=self.orc_api,cmd=request_cmd)
        data = pyjq.all(condition, url=orc_url)

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
                    "and .SQLDelay > {delaytime}) .Key.Hostname".format(delaytime=self.num)
        return self.getJsonData(condition, request_cmd)

    def getSecondsBehindMaster(self,request_cmd):
        condition = ".[] | select(.ReplicationDepth==1 and .SecondsBehindMaster.Int64 > {delaytime}) " \
                    ".Key.Hostname".format(delaytime=self.num)
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
        allNodeList = self.getAliasOfAllNode(request_cmd)
        downList = self.getClusterDownNodes(request_cmd)
        upList =  self.getClusterUpNodes(request_cmd)
        masterList =  self.getMasterNodes(request_cmd)
        behindMasterList = self.getSecondsBehindMaster(request_cmd)

        if len(downList) !=0 :
            for val in downList:
                moveNodeList.append(val)

        if len(behindMasterList) != 0:
            for val in behindMasterList:
                moveNodeList.append(val)

        if len(upList) != 0 :
            for val in masterList:
                moveNodeList.append(val)
            for val in upList:
                upNodeList.append(val)

        else:
            upNodeList.append(masterList[0])
        ###如果 所有的slave 都延迟高， 且状态up ，如果提供master服务？？？？？
        if len(moveNodeList) == len(allNodeList):
            moveNodeList.remove(masterList[0])
            return moveNodeList,masterList
        return moveNodeList,upNodeList

    def getClusterAlias(self):
        #curl  -sS http://${apiIpAndPort}/api/clusters-info | jq '.[] .ClusterAlias' -r
        reqAlias = "/clusters-info"
        condition = ".[] .ClusterAlias"
        return self.getJsonData(condition, reqAlias)

    def sedConsulTemplate(self):
        pass

if __name__ == "__main__":
    ##orchestrator配置信息
    apiIp = "10.0.34.78"
    apiPort = 3000
    consulIpAndPort = "10.0.34.78:8500"
    delaytime = 1000000

    # 文件路径
    templateFile = "./haproxy.ctmpl"
    templateFile1 = "./haproxy.ctmpl.1"
    haproxyCfg = "/etc/haproxy/haproxy.cfg"
    logfile = "/var/log/orch_hook.log"

    while True:
        flag = True
        starttime = datetime.datetime.now()
        orchook = OrcHook(apiIp,apiPort,delaytime)
        aliasList = orchook.getClusterAlias()
        moveNodeList = []
        addNodeList = []
        for val in aliasList:
            cmd = "/cluster/alias/{alias}".format(alias=val)
            offlineNodeList = orchook.getMoveOrUpClusterNode(cmd)[0]
            onlineNodeList = orchook.getMoveOrUpClusterNode(cmd)[1]

            offlineNodeList = [val + "_"+ x for x in offlineNodeList]
            onlineNodeList = [val + "_"+ x for x in onlineNodeList]
            # print("on :",onlineNodeList)
            # print("off :",offlineNodeList)
            moveNodeList += offlineNodeList
            addNodeList +=  onlineNodeList

        # print(moveNodeList)
        # print(addNodeList)

        with open(templateFile,"r") as f1,open(templateFile1,"w",encoding= 'utf8') as f2:
            for val in f1.readlines():
                for val01 in addNodeList:
                    if val01 in val:
                        if re.search('weight \d+', val).group() != "weight 10":
                            flag = False
                        val = re.sub('weight \d+',"weight 10",val)
                        # print(flag)


                for val01 in moveNodeList:
                    if val01 in val:
                        if re.search('weight \d+', val).group() != "weight 0":
                            flag = False
                        val = re.sub('weight \d+',"weight 0",val)

                f2.write(val)

        consulRestartCmd = "systemctl restart consul-template"
        haproxyReloadCmd = "systemctl reload haproxy"
        #consul-template
        print(flag)
        if flag == False:
            consulTemplateCmd = "/usr/local/bin/consul-template -consul-addr={consulIpAndPort}" \
                                " -template \"{templateFile}:{haproxycfg}\" " \
                                "-once".format(consulIpAndPort=consulIpAndPort ,templateFile=templateFile1,haproxycfg=haproxyCfg)
            consulOutCmd = subprocess.getstatusoutput(consulTemplateCmd)
            print(consulOutCmd)
            if consulOutCmd[0] != 0:
                subprocess.getstatusoutput(consulRestartCmd)

            #reload haproxy
            haproxyOutCmd = subprocess.getstatusoutput(haproxyReloadCmd)
            if haproxyOutCmd[0] != 0 :
                    subprocess.getstatusoutput(consulRestartCmd)
            else:
                subprocess.getstatusoutput("/bin/cp -rf {templateFile} {templateFile1}".format(templateFile1=templateFile1,templateFile=templateFile))
        else:
            print("没有信息更改！")
        endtime = datetime.datetime.now()
        print(endtime-starttime)
        time.sleep(1)
