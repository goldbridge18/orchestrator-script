#### script-orc

在配置haproxy的server 名称需要注意格式: alias_hostname  

- alias是orchestrator服务中为mysql设置的别名,
- hostname是mysql节点的主机名 

脚本中的 在匹配 信息时利用的上述的名称来决定修改的信息.这个格式的名称在cluster中是唯一的.
