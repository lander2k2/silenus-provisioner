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

### Control Group: `'default_control_group'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'control_cluster'` | `False` | A value of False will result in no control network or server being provisioned. Without a `control_cluster` provisioned you will command your infrastructure from your local workstation. This is acceptable during testing but if you put into actual use, especially if a team administers your infrastructure, you will need a control cluster from which to command your infrastructure assets.
`'primary_cluster_cidr'` | `'10.0.0.0/8'` | This is the network space that your containerized workloads will run in.
`'support_cluster_cidr'` | `'172.16.0.0/12'` | If you need to install software that is not containerized and/or not managed by the container orchestration system, it will be deployed in this network space.
`'control_cluster_cidr'` | `'192.168.0.0/16'` | This is the network space that your infrascture control operations will live in. This is where your logs will be aggregated, your monitoring will be federated and it is from where you will command your control group's infrastructure assets.
`'orchestrator'` | `'kubernetes'` | The orchestration tool used to manage your containerized workloads. Kubernetes is the default - and currently only supported - system.
`'platform'` | `'amazon_web_services'` | The infrastructure platform on which your systems will run. Amazon Web Services is the default - and currently only supported - platform.
`'region'` | `'us-east-1'` | The AWS region in which the control group will live.

### Tier: `'default_dev_tier'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'support_cluster'` | `False` | No support cluster for workloads running outside container orchestration by default.
`'primary_cluster_cidr'` | `'10.0.0.0/16'` | The network space for containerized workloads in the tier. Includes 65k IPs inside the tier and allows for 256 tiers per control group.
`'support_cluster_cidr'` | `'172.16.0.0/16'` | Includes 65k IPs if activated and allows for 16 tiers to have a support clusters.
`'dedicated_etcd'` | `False` | Will deploy etcd on controller nodes instead of using a dedicated etcd cluster.
`'controllers'` | `1` | A single controller node will be provisioned for clusters in this tier. This value cannot be changed on the fly. All clusters in this tier will always have a single controller.
`'initial_workers'` | `2` | The initial number of worker nodes that will be provisioned for a cluster in this tier.  The number of workers can be scaled up or down at any time on a per-cluster basis.

### Cluster: `'default_dev_01_cluster'`
configuration key | configuration value | explanation
----------------- | ------------------- | -----------
`'host_cidr'` | `'10.0.0.0/20'` | The controller and worker nodes will use IPs in this range.
`'host_subnet_cidrs'` | `['10.0.0.0/22', '10.0.4.0/22', '10.0.8.0/22', '10.0.12.0/22']` | Defines the CIDR for the maximum of four subnets. The host subnet CIDRs must fall inside the `'host_cidr'`.
`'pod_cidr'` | `'10.0.16.0/20'` | The container overlay network will use IPs in this range for the pods running your containerized workloads.
`'service_cidr'` | `'10.0.32.0/24'` | The container overlay network will use IPs in this range for the orchestration system's internal services.
`'controller_ips'` | `['10.0.0.50']` | Defines the static IP/s for the controller node. Length of array must match the number of controllers defined in the tier.
`'etcd_ips'` | `['10.0.0.50']` | Defines the static IP/s for the node on which etcd is deployed.  If not running a dedicated etcd cluster, it must be identical to the ``'controller_ips'`. Length of array must match the number of controllers defined in the tier.
`'kubernetes_api_ip'` | `'10.0.32.1'` | The static IP used for the Kubernetes API in the container's overlay network.
`'cluster_dns_ip'` | `'10.0.32.10'` | The static IP used for cluster DNS in the container's overlay network.

## Example Network Layout
The following diagram illustrates an example of the network IP configuration that could be built out if starting from the default configuration.

    ----------------------------------------------------
    | control_group alpha 10.0.0.0/8                   |
    |  ---------------------------------------------   |
    |  | tier alpha_dev 10.0.0.0/16                |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_dev_01 10.0.0.0/18   |   |   |
    |  |  | 16,384 IPs                         |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.0.0.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.0.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.4.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.8.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.12.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.0.16.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.0.32.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_dev_02 10.0.64.0/18  |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.0.64.0/20         |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.64.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.68.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.72.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.0.76.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.0.80.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.0.96.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  ---------------------------------------------   |
    |                                                  |
    |  ---------------------------------------------   |
    |  | tier alpha_stg 10.1.0.0/16                |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_stg_01 10.1.0.0/18   |   |   |
    |  |  | 16,384 IPs                         |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.1.0.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.0.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.4.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.8.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.12.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.1.16.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.1.32.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_stg_02 10.1.64.0/18  |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.1.64.0/20         |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.64.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.68.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.72.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.1.76.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.1.80.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.1.96.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  ---------------------------------------------   |
    |                                                  |
    |  ---------------------------------------------   |
    |  | tier alpha_prod 10.2.0.0/16               |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_prod_01 10.2.0.0/18  |   |   |
    |  |  | 16,384 IPs                         |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.2.0.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.0.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.4.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.8.0/22  |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.12.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.2.16.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.2.32.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  |  --------------------------------------   |   |
    |  |  | cluster alpha_prod_02 10.2.64.0/18 |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | hosts 10.2.64.0/20         |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.64.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.68.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.72.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |                            |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  |  | subnet 10.2.76.0/22 |   |    |   |   |
    |  |  |  |  | 1024 IPs            |   |    |   |   |
    |  |  |  |  -----------------------   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | pods 10.2.80.0/20          |    |   |   |
    |  |  |  | 4096 IPs                   |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |  | services 10.2.96.0/24      |    |   |   |
    |  |  |  | 256 IPs                    |    |   |   |
    |  |  |  ------------------------------    |   |   |
    |  |  |                                    |   |   |
    |  |  --------------------------------------   |   |
    |  |                                           |   |
    |  ---------------------------------------------   |
    |                                                  |
    ----------------------------------------------------

