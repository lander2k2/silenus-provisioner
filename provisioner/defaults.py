from provisioner.models import JurisdictionType, ConfigurationTemplate, UserdataTemplate


PROVISIONER_DEFAULTS = {
    'jurisdiction_types': [
        {
            'id': 1,
            'name': 'control_group',
            'description': 'A control group defines a group of infrastructural resources that are usually in a particular data center or geographic zone. A control group possesses its own private newtwork space and will usually contain several tiers.',
            'parent_id': None
        },
        {
            'id': 2,
            'name': 'tier',
            'description': 'A tier is assigned to a control group and represents a level of criticality for the workloads running in it. Common tiers are Development, Staging and Production.',
            'parent_id': 1
        },
        {
            'id': 3,
            'name': 'cluster',
            'description': 'A cluster lives in a tier and hosts containerized workloads. The clusters workloads are controlled by a container orchestration tool.',
            'parent_id': 2
        }
    ],
    'configuration_templates': [
        {
            'id': 1,
            'name': 'default_control_group',
            'configuration': {
                'control_cluster': False,  # if True provision control VPC and server
                'primary_cluster_cidr': '10.0.0.0/14',
                'support_cluster_cidr': '172.16.0.0/14',
                'control_cluster_cidr': '192.168.0.0/18',
                'orchestrator': 'kubernetes',
                'platform': 'amazon_web_services',
                'region': 'us-east-1'
            },
            'default': True,
            'jurisdiction_type_id': 1
        },
        {
            'id': 2,
            'name': 'default_dev_tier',
            'configuration': {
                'support_cluster': False,  # if True create support VPC
                'primary_cluster_cidr': '10.0.0.0/16',
                'support_cluster_cidr': '172.16.0.0/16',
                'dedicated_etcd': False,
                #'controllers': 1,
                'initial_workers': 2,
                'controller_instance_type': 'm3.medium',
                'etcd_instance_type': 'm3.medium',
                'worker_instance_type': 'm3.large'
            },
            'default': True,
            'jurisdiction_type_id': 2
        },
        {
            'id': 3,
            'name': 'default_dev_01_cluster',
            'configuration': {
                'coreos_release_channel': 'stable',
                'cluster_cidr': '10.0.0.0/18',
                'hosts_cidr': '10.0.0.0/20',
                'host_subnet_cidrs': [
                    '10.0.0.0/22',
                    '10.0.4.0/22',
                    '10.0.8.0/22',
                    '10.0.12.0/22'
                ],
                'services_cidr': '10.0.16.0/24',
                'pods_cidr': '10.0.32.0/19',
                'controller_ips': [
                    '10.0.0.50'
                ],
                'etcd_ips': [
                    '10.0.0.50'
                ],
                'kubernetes_version': '1.4.3',
                'kubernetes_api_ip': '10.0.16.1',
                'cluster_dns_ip': '10.0.16.10',
                'kubernetes_api_dns_names': [
                    'kubernetes',
                    'kubernetes.default',
                    'kubernetes.default.svc',
                    'kubernetes.default.svc.cluster.local'
                ],
                'userdata_template_ids': {
                    'controller': 1,
                    'worker': 2,
                    'etcd': 3
                }
            },
            'default': True,
            'jurisdiction_type_id': 3
        }
    ],
    'userdata_templates': [
        {
            'name': 'default_controller',
            'role': 'controller',
            'content': """#cloud-config
coreos:
  update:
    reboot-strategy: etcd-lock
  locksmith:
    window-start: Fri 22:00
    window-length: 24h
  flannel:
    interface: $private_ipv4
    etcd_endpoints: {% for ip in etcd_ips %}http://{{ ip }}:2379,{% endfor %}
  {% if not dedicated_etcd -%}
  etcd2:
    name: controller-{{ count }}
    advertise-client-urls: http://$private_ipv4:2379,http://{{ controller_elb_dns }}:2379
    initial-advertise-peer-urls: http://$private_ipv4:2380
    initial-cluster: {% set counter = 0 %}{% for ip in etcd_ips %}controller-{{ counter }}=http://{{ ip }}:2380,{% set counter = counter + 1 %}{% endfor %}
    listen-client-urls: http://0.0.0.0:2379
    listen-peer-urls: http://0.0.0.0:2380

  units:
    - name: etcd2.service
      command: start
  {%- else -%}
  units:
  {%- endif %}

    - name: docker.service
      drop-ins:
        - name: 40-flannel.conf
          content: |
            [Unit]
            Requires=flanneld.service
            After=flanneld.service

    - name: flanneld.service
      drop-ins:
        - name: 10-etcd.conf
          content: |
            [Service]
            ExecStartPre=/usr/bin/curl --silent -X PUT -d \\
            "value={\\"Network\\" : \\"{{ pods_cidr }}\\", \\"Backend\\" : {\\"Type\\" : \\"vxlan\\"}}" \\
            {% if dedicated_etcd -%}
            http://{{ etcd_elb_dns }}:2379/v2/keys/coreos.com/network/config?prevExist=false
            {%- else -%}
            http://localhost:2379/v2/keys/coreos.com/network/config?prevExist=false
            {%- endif %}

    - name: kubelet.service
      command: start
      enable: true
      content: |
        [Service]
        Environment=KUBELET_VERSION=v{{ kubernetes_version }}_coreos.0
        Environment=KUBELET_ACI=quay.io/coreos/hyperkube
        Environment="RKT_OPTS=--volume dns,kind=host,source=/etc/resolv.conf --mount volume=dns,target=/etc/resolv.conf"
        ExecStart=/usr/lib/coreos/kubelet-wrapper \\
        --api-servers=http://localhost:8080 \\
        --network-plugin-dir=/etc/kubernetes/cni/net.d \\
        --network-plugin= \\
        --register-schedulable=false \\
        --allow-privileged=true \\
        --config=/etc/kubernetes/manifests \\
        --cluster_dns={{ cluster_dns_ip }} \\
        --cluster_domain=cluster.local \\
        --cloud-provider=aws
        Restart=always
        RestartSec=10

        [Install]
        WantedBy=multi-user.target

    - name: decrypt-tls-assets.service
      enable: true
      content: |
        [Unit]
        Description=decrypt kubelet tls assets using amazon kms
        Before=kubelet.service
        After=docker.service
        Requires=docker.service

        [Service]
        Type=oneshot
        RemainAfterExit=yes
        ExecStart=/opt/bin/decrypt-tls-assets

        [Install]
        RequiredBy=kubelet.service

    - name: install-kube-system.service
      command: start
      content: |
        [Unit]
        Requires=kubelet.service docker.service
        After=kubelet.service docker.service

        [Service]
        Type=simple
        StartLimitInterval=0
        Restart=on-failure
        ExecStartPre=/usr/bin/curl http://127.0.0.1:8080/version
        ExecStart=/opt/bin/install-kube-system

write_files:
  - path: /opt/bin/install-kube-system
    permissions: 0700
    owner: root:root
    content: |
      #!/bin/bash -e
      /usr/bin/curl  -H "Content-Type: application/json" -XPOST \\
      -d @"/srv/kubernetes/manifests/kube-dns-rc.json" \\
      "http://127.0.0.1:8080/api/v1/namespaces/kube-system/replicationcontrollers"

      /usr/bin/curl  -H "Content-Type: application/json" -XPOST \\
      -d @"/srv/kubernetes/manifests/kube-dashboard-rc.json" \\
      "http://127.0.0.1:8080/api/v1/namespaces/kube-system/replicationcontrollers"

      /usr/bin/curl  -H "Content-Type: application/json" -XPOST \\
      -d @"/srv/kubernetes/manifests/heapster-de.json" \\
      "http://127.0.0.1:8080/apis/extensions/v1beta1/namespaces/kube-system/deployments"

      for manifest in {kube-dns,heapster,kube-dashboard}-svc.json;do
          /usr/bin/curl  -H "Content-Type: application/json" -XPOST \\
          -d @"/srv/kubernetes/manifests/$manifest" \\
          "http://127.0.0.1:8080/api/v1/namespaces/kube-system/services"
      done

  - path: /opt/bin/decrypt-tls-assets
    owner: root:root
    permissions: 0700
    content: |
      #!/bin/bash -e

      for encKey in $(find /etc/kubernetes/ssl/*.pem.enc);do
        tmpPath="/tmp/$(basename $encKey).tmp"
        docker run --rm -v /etc/kubernetes/ssl:/etc/kubernetes/ssl --rm quay.io/coreos/awscli aws --region {{ region }} kms decrypt --ciphertext-blob fileb://$encKey --output text --query Plaintext | base64 --decode > $tmpPath
        mv  $tmpPath /etc/kubernetes/ssl/$(basename $encKey .enc)
      done

  - path: /etc/kubernetes/manifests/kube-proxy.yaml
    content: |
        apiVersion: v1
        kind: Pod
        metadata:
          name: kube-proxy
          namespace: kube-system
        spec:
          hostNetwork: true
          containers:
          - name: kube-proxy
            image: quay.io/coreos/hyperkube:v{{ kubernetes_version }}_coreos.0
            command:
            - /hyperkube
            - proxy
            - --master=http://127.0.0.1:8080
            securityContext:
              privileged: true
            volumeMounts:
            - mountPath: /etc/ssl/certs
              name: ssl-certs-host
              readOnly: true
          volumes:
          - hostPath:
              path: /usr/share/ca-certificates
            name: ssl-certs-host

  - path: /etc/kubernetes/manifests/kube-apiserver.yaml
    content: |
      apiVersion: v1
      kind: Pod
      metadata:
        name: kube-apiserver
        namespace: kube-system
      spec:
        hostNetwork: true
        containers:
        - name: kube-apiserver
          image: quay.io/coreos/hyperkube:v{{ kubernetes_version }}_coreos.0
          command:
          - /hyperkube
          - apiserver
          - --bind-address=0.0.0.0
          - --etcd-servers={% for ip in etcd_ips %}http://{{ ip }}:2379,{% endfor %}
          - --allow-privileged=true
          - --service-cluster-ip-range={{ services_cidr }}
          - --secure-port=443
          - --advertise-address=$private_ipv4
          - --admission-control=NamespaceLifecycle,LimitRanger,ServiceAccount,ResourceQuota
          - --tls-cert-file=/etc/kubernetes/ssl/apiserver.pem
          - --tls-private-key-file=/etc/kubernetes/ssl/apiserver-key.pem
          - --client-ca-file=/etc/kubernetes/ssl/ca.pem
          - --service-account-key-file=/etc/kubernetes/ssl/apiserver-key.pem
          - --runtime-config=extensions/v1beta1/networkpolicies=true
          - --cloud-provider=aws
          livenessProbe:
            httpGet:
              host: 127.0.0.1
              port: 8080
              path: /healthz
            initialDelaySeconds: 15
            timeoutSeconds: 15
          ports:
          - containerPort: 443
            hostPort: 443
            name: https
          - containerPort: 8080
            hostPort: 8080
            name: local
          volumeMounts:
          - mountPath: /etc/kubernetes/ssl
            name: ssl-certs-kubernetes
            readOnly: true
          - mountPath: /etc/ssl/certs
            name: ssl-certs-host
            readOnly: true
        volumes:
        - hostPath:
            path: /etc/kubernetes/ssl
          name: ssl-certs-kubernetes
        - hostPath:
            path: /usr/share/ca-certificates
          name: ssl-certs-host

  - path: /etc/kubernetes/manifests/kube-controller-manager.yaml
    content: |
      apiVersion: v1
      kind: Pod
      metadata:
        name: kube-controller-manager
        namespace: kube-system
      spec:
        containers:
        - name: kube-controller-manager
          image: quay.io/coreos/hyperkube:v{{ kubernetes_version }}_coreos.0
          command:
          - /hyperkube
          - controller-manager
          - --master=http://127.0.0.1:8080
          - --leader-elect=true
          - --service-account-private-key-file=/etc/kubernetes/ssl/apiserver-key.pem
          - --root-ca-file=/etc/kubernetes/ssl/ca.pem
          - --cloud-provider=aws
          resources:
            requests:
              cpu: 200m
          livenessProbe:
            httpGet:
              host: 127.0.0.1
              path: /healthz
              port: 10252
            initialDelaySeconds: 15
            timeoutSeconds: 15
          volumeMounts:
          - mountPath: /etc/kubernetes/ssl
            name: ssl-certs-kubernetes
            readOnly: true
          - mountPath: /etc/ssl/certs
            name: ssl-certs-host
            readOnly: true
        hostNetwork: true
        volumes:
        - hostPath:
            path: /etc/kubernetes/ssl
          name: ssl-certs-kubernetes
        - hostPath:
            path: /usr/share/ca-certificates
          name: ssl-certs-host

  - path: /etc/kubernetes/manifests/kube-scheduler.yaml
    content: |
      apiVersion: v1
      kind: Pod
      metadata:
        name: kube-scheduler
        namespace: kube-system
      spec:
        hostNetwork: true
        containers:
        - name: kube-scheduler
          image: quay.io/coreos/hyperkube:v{{ kubernetes_version }}_coreos.0
          command:
          - /hyperkube
          - scheduler
          - --master=http://127.0.0.1:8080
          - --leader-elect=true
          resources:
            requests:
              cpu: 100m
          livenessProbe:
            httpGet:
              host: 127.0.0.1
              path: /healthz
              port: 10251
            initialDelaySeconds: 15
            timeoutSeconds: 15

  - path: /srv/kubernetes/manifests/kube-dns-rc.json
    content: |
        {
          "apiVersion": "v1",
          "kind": "ReplicationController",
          "metadata": {
            "labels": {
              "k8s-app": "kube-dns",
              "kubernetes.io/cluster-service": "true",
              "version": "v15"
            },
            "name": "kube-dns-v15",
            "namespace": "kube-system"
          },
          "spec": {
            "replicas": 1,
            "selector": {
              "k8s-app": "kube-dns",
              "version": "v15"
            },
            "template": {
              "metadata": {
                "labels": {
                  "k8s-app": "kube-dns",
                  "kubernetes.io/cluster-service": "true",
                  "version": "v15"
                }
              },
              "spec": {
                "containers": [
                  {
                    "args": [
                      "--domain=cluster.local.",
                      "--dns-port=10053"
                    ],
                    "image": "gcr.io/google_containers/kubedns-amd64:1.3",
                    "livenessProbe": {
                      "failureThreshold": 5,
                      "httpGet": {
                        "path": "/healthz",
                        "port": 8080,
                        "scheme": "HTTP"
                      },
                      "initialDelaySeconds": 60,
                      "successThreshold": 1,
                      "timeoutSeconds": 5
                    },
                    "name": "kubedns",
                    "ports": [
                      {
                        "containerPort": 10053,
                        "name": "dns-local",
                        "protocol": "UDP"
                      },
                      {
                        "containerPort": 10053,
                        "name": "dns-tcp-local",
                        "protocol": "TCP"
                      }
                    ],
                    "readinessProbe": {
                      "httpGet": {
                        "path": "/readiness",
                        "port": 8081,
                        "scheme": "HTTP"
                      },
                      "initialDelaySeconds": 30,
                      "timeoutSeconds": 5
                    },
                    "resources": {
                      "limits": {
                        "cpu": "100m",
                        "memory": "200Mi"
                      },
                      "requests": {
                        "cpu": "100m",
                        "memory": "50Mi"
                      }
                    }
                  },
                  {
                    "args": [
                      "--cache-size=1000",
                      "--no-resolv",
                      "--server=127.0.0.1#10053"
                    ],
                    "image": "gcr.io/google_containers/kube-dnsmasq-amd64:1.3",
                    "name": "dnsmasq",
                    "ports": [
                      {
                        "containerPort": 53,
                        "name": "dns",
                        "protocol": "UDP"
                      },
                      {
                        "containerPort": 53,
                        "name": "dns-tcp",
                        "protocol": "TCP"
                      }
                    ]
                  },
                  {
                    "args": [
                      "-cmd=nslookup kubernetes.default.svc.cluster.local 127.0.0.1 >/dev/null",
                      "-port=8080",
                      "-quiet"
                    ],
                    "image": "gcr.io/google_containers/exechealthz-amd64:1.0",
                    "name": "healthz",
                    "ports": [
                      {
                        "containerPort": 8080,
                        "protocol": "TCP"
                      }
                    ],
                    "resources": {
                      "limits": {
                        "cpu": "10m",
                        "memory": "20Mi"
                      },
                      "requests": {
                        "cpu": "10m",
                        "memory": "20Mi"
                      }
                    }
                  }
                ],
                "dnsPolicy": "Default"
              }
            }
          }
        }

  - path: /srv/kubernetes/manifests/kube-dns-svc.json
    content: |
        {
          "apiVersion": "v1",
          "kind": "Service",
          "metadata": {
            "name": "kube-dns",
            "namespace": "kube-system",
            "labels": {
              "k8s-app": "kube-dns",
              "kubernetes.io/name": "KubeDNS",
              "kubernetes.io/cluster-service": "true"
            }
          },
          "spec": {
            "clusterIP": "{{ cluster_dns_ip }}",
            "ports": [
              {
                "protocol": "UDP",
                "name": "dns",
                "port": 53
              },
              {
                "protocol": "TCP",
                "name": "dns-tcp",
                "port": 53
              }
            ],
            "selector": {
              "k8s-app": "kube-dns"
            }
          }
        }

  - path: /srv/kubernetes/manifests/heapster-de.json
    content: |
        {
          "apiVersion": "extensions/v1beta1",
          "kind": "Deployment",
          "metadata": {
            "labels": {
              "k8s-app": "heapster",
              "kubernetes.io/cluster-service": "true",
              "version": "v1.1.0"
            },
            "name": "heapster-v1.1.0",
            "namespace": "kube-system"
          },
          "spec": {
            "replicas": 1,
            "selector": {
              "matchLabels": {
                "k8s-app": "heapster",
                "version": "v1.1.0"
              }
            },
            "template": {
              "metadata": {
                "labels": {
                  "k8s-app": "heapster",
                  "version": "v1.1.0"
                }
              },
              "spec": {
                "containers": [
                  {
                    "command": [
                      "/heapster",
                      "--source=kubernetes.summary_api:''"
                    ],
                    "image": "gcr.io/google_containers/heapster:v1.1.0",
                    "name": "heapster",
                    "resources": {
                      "limits": {
                        "cpu": "100m",
                        "memory": "200Mi"
                      },
                      "requests": {
                        "cpu": "100m",
                        "memory": "200Mi"
                      }
                    }
                  },
                  {
                    "command": [
                      "/pod_nanny",
                      "--cpu=100m",
                      "--extra-cpu=0.5m",
                      "--memory=200Mi",
                      "--extra-memory=4Mi",
                      "--threshold=5",
                      "--deployment=heapster-v1.1.0",
                      "--container=heapster",
                      "--poll-period=300000",
                      "--estimator=exponential"
                    ],
                    "env": [
                      {
                        "name": "MY_POD_NAME",
                        "valueFrom": {
                          "fieldRef": {
                            "fieldPath": "metadata.name"
                          }
                        }
                      },
                      {
                        "name": "MY_POD_NAMESPACE",
                        "valueFrom": {
                          "fieldRef": {
                            "fieldPath": "metadata.namespace"
                          }
                        }
                      }
                    ],
                    "image": "gcr.io/google_containers/addon-resizer:1.3",
                    "name": "heapster-nanny",
                    "resources": {
                      "limits": {
                        "cpu": "50m",
                        "memory": "100Mi"
                      },
                      "requests": {
                        "cpu": "50m",
                        "memory": "100Mi"
                      }
                    }
                  }
                ]
              }
            }
          }
        }

  - path: /srv/kubernetes/manifests/heapster-svc.json
    content: |
        {
          "kind": "Service",
          "apiVersion": "v1",
          "metadata": {
            "name": "heapster",
            "namespace": "kube-system",
            "labels": {
              "kubernetes.io/cluster-service": "true",
              "kubernetes.io/name": "Heapster"
            }
          },
          "spec": {
            "ports": [
              {
                "port": 80,
                "targetPort": 8082
              }
            ],
            "selector": {
              "k8s-app": "heapster"
            }
          }
        }

  - path: /srv/kubernetes/manifests/kube-dashboard-rc.json
    content: |
        {
          "apiVersion": "v1",
          "kind": "ReplicationController",
          "metadata": {
            "labels": {
              "k8s-app": "kubernetes-dashboard",
              "kubernetes.io/cluster-service": "true",
              "version": "v1.1.0"
            },
            "name": "kubernetes-dashboard-v1.1.0",
            "namespace": "kube-system"
          },
          "spec": {
            "replicas": 1,
            "selector": {
              "k8s-app": "kubernetes-dashboard"
            },
            "template": {
              "metadata": {
                "labels": {
                  "k8s-app": "kubernetes-dashboard",
                  "kubernetes.io/cluster-service": "true",
                  "version": "v1.1.0"
                }
              },
              "spec": {
                "containers": [
                  {
                    "image": "gcr.io/google_containers/kubernetes-dashboard-amd64:v1.1.0",
                    "livenessProbe": {
                      "httpGet": {
                        "path": "/",
                        "port": 9090
                      },
                      "initialDelaySeconds": 30,
                      "timeoutSeconds": 30
                    },
                    "name": "kubernetes-dashboard",
                    "ports": [
                      {
                        "containerPort": 9090
                      }
                    ],
                    "resources": {
                      "limits": {
                        "cpu": "100m",
                        "memory": "50Mi"
                      },
                      "requests": {
                        "cpu": "100m",
                        "memory": "50Mi"
                      }
                    }
                  }
                ]
              }
            }
          }
        }

  - path: /srv/kubernetes/manifests/kube-dashboard-svc.json
    content: |
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "labels": {
                    "k8s-app": "kubernetes-dashboard",
                    "kubernetes.io/cluster-service": "true"
                },
                "name": "kubernetes-dashboard",
                "namespace": "kube-system"
            },
            "spec": {
                "ports": [
                    {
                        "port": 80,
                        "targetPort": 9090
                    }
                ],
                "selector": {
                    "k8s-app": "kubernetes-dashboard"
                }
            }
        }

  - path: /etc/kubernetes/ssl/ca.pem.enc
    encoding: gzip+base64
    content: {{ enc_cluster_ca }}

  - path: /etc/kubernetes/ssl/apiserver.pem.enc
    encoding: gzip+base64
    content: {{ enc_apiserver_cert }}

  - path: /etc/kubernetes/ssl/apiserver-key.pem.enc
    encoding: gzip+base64
    content: {{ enc_apiserver_key }}

"""
        },
        {
            'name': 'default_worker',
            'role': 'worker',
            'content': """#cloud-config
coreos:
  update:
    reboot-strategy: etcd-lock
  locksmith:
    window-start: Fri 22:00
    window-length: 24h
  flannel:
    interface: $private_ipv4
    etcd_endpoints: {% for ip in etcd_ips %}http://{{ ip }}:2379,{% endfor %}
  units:
    - name: docker.service
      drop-ins:
        - name: 40-flannel.conf
          content: |
            [Unit]
            Requires=flanneld.service
            After=flanneld.service

    - name: kubelet.service
      enable: true
      command: start
      content: |
        [Service]
        Environment=KUBELET_VERSION=v{{ kubernetes_version }}_coreos.0
        Environment=KUBELET_ACI=quay.io/coreos/hyperkube
        Environment="RKT_OPTS=--volume dns,kind=host,source=/etc/resolv.conf --mount volume=dns,target=/etc/resolv.conf"
        ExecStart=/usr/lib/coreos/kubelet-wrapper \\
        --api-servers=https://{{ controller_elb_dns }}:443 \\
        --network-plugin-dir=/etc/kubernetes/cni/net.d \\
        --network-plugin= \\
        --register-node=true \\
        --allow-privileged=true \\
        --config=/etc/kubernetes/manifests \\
        --cluster_dns={{ cluster_dns_ip }} \\
        --cluster_domain=cluster.local \\
        --cloud-provider=aws \\
        --kubeconfig=/etc/kubernetes/worker-kubeconfig.yaml \\
        --tls-cert-file=/etc/kubernetes/ssl/worker.pem \\
        --tls-private-key-file=/etc/kubernetes/ssl/worker-key.pem
        Restart=always
        RestartSec=10
        [Install]
        WantedBy=multi-user.target

    - name: decrypt-tls-assets.service
      enable: true
      content: |
        [Unit]
        Description=decrypt kubelet tls assets using amazon kms
        Before=kubelet.service
        After=docker.service
        Requires=docker.service

        [Service]
        Type=oneshot
        RemainAfterExit=yes
        ExecStart=/opt/bin/decrypt-tls-assets

        [Install]
        RequiredBy=kubelet.service

write_files:
  - path: /etc/kubernetes/ssl/ca.pem.enc
    encoding: gzip+base64
    content: {{ enc_cluster_ca }}

  - path: /etc/kubernetes/ssl/worker.pem.enc
    encoding: gzip+base64
    content: {{ enc_worker_cert }}

  - path: /etc/kubernetes/ssl/worker-key.pem.enc
    encoding: gzip+base64
    content: {{ enc_worker_key }}

  - path: /opt/bin/decrypt-tls-assets
    owner: root:root
    permissions: 0700
    content: |
      #!/bin/bash -e

      for encKey in $(find /etc/kubernetes/ssl/*.pem.enc);do
        tmpPath="/tmp/$(basename $encKey).tmp"
        docker run --rm -v /etc/kubernetes/ssl:/etc/kubernetes/ssl --rm quay.io/coreos/awscli aws --region {{ region }} kms decrypt --ciphertext-blob fileb://$encKey --output text --query Plaintext | base64 --decode > $tmpPath
        mv  $tmpPath /etc/kubernetes/ssl/$(basename $encKey .enc)
      done

  - path: /etc/kubernetes/manifests/kube-proxy.yaml
    content: |
        apiVersion: v1
        kind: Pod
        metadata:
          name: kube-proxy
          namespace: kube-system
        spec:
          hostNetwork: true
          containers:
          - name: kube-proxy
            image: quay.io/coreos/hyperkube:v{{ kubernetes_version }}_coreos.0
            command:
            - /hyperkube
            - proxy
            - --master=https://{{ controller_elb_dns }}:443
            - --kubeconfig=/etc/kubernetes/worker-kubeconfig.yaml
            securityContext:
              privileged: true
            volumeMounts:
              - mountPath: /etc/ssl/certs
                name: "ssl-certs"
              - mountPath: /etc/kubernetes/worker-kubeconfig.yaml
                name: "kubeconfig"
                readOnly: true
              - mountPath: /etc/kubernetes/ssl
                name: "etc-kube-ssl"
                readOnly: true
          volumes:
            - name: "ssl-certs"
              hostPath:
                path: "/usr/share/ca-certificates"
            - name: "kubeconfig"
              hostPath:
                path: "/etc/kubernetes/worker-kubeconfig.yaml"
            - name: "etc-kube-ssl"
              hostPath:
                path: "/etc/kubernetes/ssl"

  - path: /etc/kubernetes/worker-kubeconfig.yaml
    content: |
        apiVersion: v1
        kind: Config
        clusters:
        - name: local
          cluster:
            certificate-authority: /etc/kubernetes/ssl/ca.pem
        users:
        - name: kubelet
          user:
            client-certificate: /etc/kubernetes/ssl/worker.pem
            client-key: /etc/kubernetes/ssl/worker-key.pem
        contexts:
        - context:
            cluster: local
            user: kubelet
          name: kubelet-context
        current-context: kubelet-context

"""
        },
        {
            'name': 'default_etcd',
            'role': 'etcd',
            'content': """#cloud-config
coreos:
  update:
    reboot-strategy: etcd-lock
  locksmith:
    window-start: Fri 22:00
    window-length: 24h
  etcd2:
    name: etcd-{{ increment }}
    advertise-client-urls: http://$private_ipv4:2379,http://{{ etcd_elb_dns }}:2379
    initial-advertise-peer-urls: http://$private_ipv4:2380
    initial-cluster: {% set counter = 0 %}{% for ip in etcd_ips %}controller-{{ counter }}=http://{{ ip }}:2380,{% set counter = counter + 1 %}{% endfor %}
    listen-client-urls: http://0.0.0.0:2379
    listen-peer-urls: http://0.0.0.0:2380
  units:
    - name: etcd2.service
      command: start

"""
        }
    ]
}


def load_defaults(db):
    """
    Adds default jurisdiction types:
      * control_group
      * tier
      * cluster
    Adds default configuration for each of the three jurisdiction types
    Adds default userdata templates
    """
    pd = PROVISIONER_DEFAULTS

    # jurisdiction types
    for jt in PROVISIONER_DEFAULTS['jurisdiction_types']:
        with db.transaction() as session:
            session.add(JurisdictionType(name=jt['name'],
                                         description=jt['description'],
                                         parent_id=jt['parent_id']))

    # configurations
    with db.transaction() as session:
        for conf in PROVISIONER_DEFAULTS['configuration_templates']:
            session.add(ConfigurationTemplate(
                                name=conf['name'],
                                configuration=conf['configuration'],
                                default=conf['default'],
                                jurisdiction_type_id=conf['jurisdiction_type_id']))

        for userdata in PROVISIONER_DEFAULTS['userdata_templates']:
            session.add(UserdataTemplate(
                                name=userdata['name'],
                                role=userdata['role'],
                                content=userdata['content']))

