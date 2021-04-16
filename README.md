#### script-orc

orchestrator is a MySQL high availability and replication management tool, runs as a service and provides command line access, HTTP API and Web interface

在配置haproxy的server 名称需要注意格式: alias_hostname  

- alias是orchestrator服务中为mysql设置的别名,
- hostname是mysql节点的主机名 

脚本中的 在匹配 信息时利用的上述的名称来决定修改的信息.这个格式的名称在cluster中是唯一的.

> **脚本中的原则是:在读写分离时,只要有一个slave能提供读的服务,则master就不向读端口提供服务**
