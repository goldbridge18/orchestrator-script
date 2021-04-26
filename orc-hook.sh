#!/bin/bash

#change master to master_host='tidb2',master_user='rep',master_password='rep123',MASTER_AUTO_POSITION=1,MASTER_HEARTBEAT_PERIOD=2,master_port=61106,MASTER_CONNECT_RETRY=1,MASTER_RETRY_COUNT=86400;

apiIpAndPort="10.0.34.78:3000"
consulIpAndPort="10.0.34.78:8500"
isitdead="DeadMaster"
delaytime=100
mysqlport=61106

#文件路径
templateFile="/etc/consul-template/templates/haproxy.ctmpl"
haproxycfg="/etc/haproxy/haproxy.cfg"
logfile="/var/log/orch_hook.log"

#找到down掉的slave节点,输出一个数组
getDownReplicasList(){
	#返回值为 templateFile路径的文件，down的节点配置信息所对应的行号
	replicasDownHostName=`curl  -sS http://${apiIpAndPort}/api/cluster/alias/$1 | jq '.[] | select((.Slave_IO_Running==false or .Slave_SQL_Running==false) and .ReplicationDepth==1) .Key.Hostname' -r`
    for value in $replicasDownHostName;do
		num=`grep -n "$1_$value"  $templateFile | awk -F':' '{print $1}'`
		arr[${#arr[@]}]=$num
    done
    echo ${arr[*]}
}

#找到所有slave的UP 状态的节点
getUpReplicasList(){
	#返回值为 templateFile路径的文件，down的节点配置信息所对应的行号
    #downNodeList=$(getDownReplicasList $1)
	replicasUpHostName=`curl  -sS http://${apiIpAndPort}/api/cluster/alias/$1 | jq '.[] | select(.Slave_IO_Running==true and .Slave_SQL_Running==true and .ReplicationDepth==1) .Key.Hostname' -r`
	
    for value in $replicasUpHostName;do
	    #https://gist.github.com/likohank/5dec12b808d6b3577dd9d8b3bb6a22b5 判断某个元素是否在数组里
		#if [[ ! "${downNodeList}" =~ "${value}" ]]; then 
		#fi 
		num=`grep -n "$1_$value"  $templateFile | awk -F':' '{print $1}'`
		arr[${#arr[@]}]=$num
    done
    echo ${arr[*]}
}

getMasterNode(){
	masterHostName=`curl  -sS http://${apiIpAndPort}/api/cluster/alias/$1 | jq '.[] | select(.ReplicationDepth==0) .Key.Hostname' -r `
	num=`grep -n "$1_$masterHostName"  $templateFile | awk -F':' '{print $1}'`
	arr[${#arr[@]}]=$num
	echo ${arr[*]}
}

getMoveClusterNode(){
	#已经不在cluster 中的节点
    allNum=(`grep -n "$1_"  $templateFile | awk -F':' '{print $1}'`)
    masterNum=$(getMasterNode $1)
    upNum=$(getUpReplicasList $1)

    index=0
    for i in ${allNum[*]};do
       #echo "value: $i ,index: $index, Byindex: ${allNum[$index]}"
       for ii in $upNum;do
            if [[ ${allNum[$index]} == $ii ]];then
               unset allNum[$index]
            fi
       done
       for ii in $masterNum;do
            if [[ ${allNum[$index]} == $ii ]];then
               unset allNum[$index]
            fi
       done
       index=`expr $index + 1`
    done
    echo ${allNum[*]}
}

getDelayReplica(){
	
	#获取延迟库的主机名列表
	dalayHostName=`curl  -sS http://${apiIpAndPort}/api/cluster/alias/$1 | jq ".[] | select(.Slave_IO_Running==true and .Slave_SQL_Running==true and .ReplicationDepth==1 and .SQLDelay > ${delaytime}) .Key.Hostname" -r`
	
	for val in $dalayHostName;do
		num=`grep -n "$1_$val"  $templateFile | awk -F':' '{print $1}'`
		arr[${#arr[@]}]=$num
	done
	echo ${arr[*]}
}


checkHostStatus(){
	clusterAlias=$(getClusterAlias) 
	for val in $clusterAlias;do
		moveNode=$(getMoveClusterNode $val)
		arr[${#arr[@]}]=$moveNode
	done
	
	#upNodeList=$(getUpReplicasList  $1)
	#masterNode=$(getMasterNode $1)
	#moveNode=$(getMoveClusterNode $1)
	#echo moveNode: $moveNode
	#echo masterNode: $masterNode
	#echo upNodeList: $upNodeList
	echo ${arr[*]}
}

getClusterAlias(){
	#获取cluster别名
	aliasNames=`curl  -sS http://${apiIpAndPort}/api/clusters-info | jq '.[] .ClusterAlias' -r`
	for val in $aliasNames;do
		curl  -sS http://${apiIpAndPort}/api/cluster/alias/$val | jq '.[] | select(.ReplicationDepth==0) .Key.Hostname' -r >/dev/null 2>&1
		if [ $? -eq 0 ]; then
			arr[${#arr[@]}]=$val
		fi
	done
	echo ${arr[*]}
}


setReplicaOnlyRead(){
	#设置只读 $1 别名
	replicasUpHostName=`curl  -sS http://${apiIpAndPort}/api/cluster/alias/$1 | jq '.[] | select(.Slave_IO_Running==true and .Slave_SQL_Running==true and .ReplicationDepth==1 and .ReadOnly==false) .Key.Hostname' -r`
	if [ $? -eq 1 ];then
		replicasUpHostName=""
	fi
	if [[ $replicasUpHostName ]];then
		
		for val in $replicasUpHostName;do
			curl  -sS http://${apiIpAndPort}/api/set-read-only/${val}/${mysqlport} >>$logfile
			echo `date "+%Y-%m-%d %H:%M:%S"` "$val set only read!!" >>$logfile
		done
	fi
}

setHaproxyTmeplate(){
	#修改consul-template的模板文件
	#找到down掉的slave节点：
	count=0
	downNodeList=$(getDownReplicasList  $1)
	echo `date "+%Y-%m-%d %H:%M:%S"` "down:$downNodeList" #>> $logfile
	
	if [[ $downNodeList ]];then
	
		for num in $downNodeList;do
			echo `date "+%Y-%m-%d %H:%M:%S"` "info: 修改consul template模板中${val} 的weight值！" >> $logfile 
			sed -i "${num}s/weight [0-9]*/weight 0/" $templateFile
		done
	fi
	
	#如果所有的slave节点都宕机了，需要把master提供给读端口访问
	upNodeList=$(getUpReplicasList  $1)
	masterNode=$(getMasterNode $1)
	moveNode=$(getMoveClusterNode $1)
	delayNode=$(getDelayReplica $1)
	echo moveNode: $moveNode		>> $logfile
	echo masterNode: $masterNode    >> $logfile
	echo upNodeList: $upNodeList    >> $logfile
	echo delayNode: $delayNode      >> $logfile
	
	if [[ $upNodeList && -n "$masterNode" ]];then
		
		#echo `date "+%Y-%m-%d %H:%M:%S"` "info: 修改consul template模板中${masterNode} 的weight值！" >> $logfile
		sed -i "${masterNode}s/weight [0-9]*/weight 0/" $templateFile
		
		for val in $upNodeList;do
			sed -i "${val}s/weight [0-9]*/weight 10/" $templateFile
		done
		
		if [[ $moveNode ]];then
			for val in $moveNode;do
				sed -i "${val}s/weight [0-9]*/weight 0/" $templateFile
			done
		fi
	elif [[ -n "$masterNode" ]];then
		#一个cluster中所有的slave节点都宕机
		#echo `date '+%Y-%m-%d %H:%M:%S'`" command: grep $1_${masterNode} $templateFile|sed 's/weight [0-9]*/weight 10/g'" >> $logfile
		echo `date "+%Y-%m-%d %H:%M:%S"` "info: 修改consul template模板中${masterNode} 的weight值！" >> $logfile

		#master的在read端口下提供服务
		sed -i "${masterNode}s/weight [0-9]*/weight 100/" $templateFile
		
		if [[ $moveNode ]];then
			for val in $moveNode;do
				sed -i "${val}s/weight [0-9]*/weight 0/" $templateFile
			done
		fi
	else
		echo ".......null..........."
	fi

	#延迟处理
	if [[ $delayNode ]];then
		
		for num in $upNodeList;do
			count=`expr $count + 1`
		done

		if [ $count -gt 1 ];then #大于
			echo `date "+%Y-%m-%d %H:%M:%S"` "replica delay too loog ,closed!!"
			for val in $delayNode;do
				sed -i "${val}s/weight [0-9]*/weight 0/" $templateFile
			done
		else
			sed -i "${masterNode}s/weight [0-9]*/weight 100/" $templateFile
			for val in $delayNode;do
				sed -i "${val}s/weight [0-9]*/weight 0/" $templateFile
			done
			
		fi
		
	fi
}

if [[ $isitdead == "DeadMaster" ]]; then

	clusterAlias=$(getClusterAlias) 
	echo `date "+%Y-%m-%d %H:%M:%S"` "----------start--------------" >> $logfile
	
	for val in $clusterAlias;do
		setHaproxyTmeplate $val
	done
	
	#for val in $clusterAlias;do
	#	setReplicaOnlyRead $val
	#done
	
	#检查是否需要修改

	template=`grep "server " $templateFile|grep -v "server master"`
	haproxy=`grep "server " $haproxycfg|grep -v "server master"`
	if [[ $template == $haproxy ]];then
		echo `date "+%Y-%m-%d %H:%M:%S"` "mysql状态检查正常！" >> $logfile
	else
		echo `date "+%Y-%m-%d %H:%M:%S"` "go...." >> $logfile
		echo `date "+%Y-%m-%d %H:%M:%S"` "替换haproxy的配置文件！" >> $logfile
		#更新模板
		rm -rf /etc/haproxy/haproxy.cfg.1
		cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.1
		/usr/local/bin/consul-template -consul-addr=${consulIpAndPort} -template "$templateFile:${haproxycfg}" -once
		systemctl reload haproxy
		
	fi
	
	echo `date "+%Y-%m-%d %H:%M:%S"` "----------end--------------" >> $logfile
	
elif [[ $isitdead == "DeadIntermediateMasterWithSingleSlaveFailingToConnect" ]]; then

	echo $(date)
	echo "Revocering from: $isitdead"
	echo "New intermediate master is: slavehost"

elif [[ $isitdead == "DeadIntermediateMaster" ]]; then

	echo $(date)
	echo "Revocering from: $isitdead"
	echo "New intermediate master is: newintermediatemaster"
fi
