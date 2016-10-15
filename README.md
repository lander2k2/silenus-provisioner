# Silenus Provisioner

Silenus is a distributed infrastructure orchestration application.

The Silenus Provisioner is a REST API that manages the configuration and
provisoining of infrastructure assets.

Supported container orchestration:
* Kubernetes

Supported infrastructure platforms:
* AWS

## Defaults
The provisioner comes with a set of default configuration templates pre-loaded.
You can use these default values, unchanged, to provision infrastructure for
research and testing.  And you can add your own configuration templates to
extend and customize your infrastructure to your needs.

### Control Group: `'alpha'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'control_cluster'` | `False` | A value of False will result in no control network or server being provisioned. Without a `control_cluster` provisioned you will command your infrastructure from your local workstation. This is acceptable during testing but if you put into actual use, especially if a team administers your infrastructure, you will need a control cluster from which to command your infrastructure assets.
`'primary_cluster_cidr'` | `'10.0.0.0/8'` | This is the network space that your containerized workloads will run in.
`'support_cluster_cidr'` | `'172.16.0.0/12'` | If you need to install software that is not containerized and/or not managed by the container orchestration system, it will be deployed in this network space.
`'control_cluster_cidr'` | `'192.168.0.0/16'` | This is the network space that your infrascture control operations will live in. This is where your logs will be aggregated, your monitoring will be federated and it is from where you will command your control group's infrastructure assets.
`'orchestrator'` | `'kubernetes'` | The orchestration tool used to manage your containerized workloads. Kubernetes is the default - and currently only supported - system.
`'platform'` | `'amazon_web_services'` | The infrastructure platform on which your systems will run. Amazon Web Services is the default - and currently only supported - platform.
`'region'` | `'us-east-1'` | The AWS region in which the control group will live.

### Tier: `'alpha_dev'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'support_cluster'` | `False` | No support cluster for workloads running outside container orchestration by default.
`'primary_cluster_cidr'` | `'10.0.0.0/11'` | Includes over 2 million IPs inside the tier and allows for 8 tiers per control group.
`'support_cluster_cidr'` | `'172.16.0.0/15'` | Includes 130k IPs if activated and allows for 8 tiers per control group.
`'dedicated_etcd'` | `False` | Will deploy etcd on controller nodes instead of using a dedicated etcd cluster.
`'controllers'` | `1` | A single controller node will be provisioned for clusters in this tier. This value cannot be changed on the fly. All clusters in this tier will always have a single controller.
`'initial_workers'` | `2` | The initial number of worker nodes that will be provisioned for a cluster in this tier.  The number of workers can be scaled up or down at any time on a per-cluster basis.

### Cluster: `'alpha_dev_01'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'host_cidr'` | `'10.0.0.0/16'` | The controller and worker nodes will use IPs in this range.
`'pod_cidr'` | `'10.1.0.0/16'` | The container overlay network will use IPs in this range for the pods running your containerized workloads.
`'service_cidr'` | `'10.2.0.0/24'` | The container overlay network will use IPs in this range for the orchestration system's interanl services.
`'host_subnet_cidrs'` | `['10.0.0.0/19', '10.0.32.0/19']` | Defines the CIDR for two subnets. Subnets can be added prior to provisioning by adding addtional valid CIDRs. They must fall inside the `'host_cidr'`.
`'controller_ips'` | `['10.0.0.50']` | Defines the static IP/s for the controller node. Length of array must match the number of controllers defined in the tier.
`'etcd_ips'` | `['10.0.0.50']` | Defines the static IP/s for the node on which etcd is deployed.  If not running a dedicated etcd cluster, it must be identical to the ``'controller_ips'`. Length of array must match the number of controllers defined in the tier.
`'kubernetes_api_ip'` | `'10.2.0.1'` | The static IP used for the Kubernetes API in the container's overlay network.
`'cluster_dns_ip'` | `'10.2.0.10'` | The static IP used for cluster DNS in the container's overlay network.

