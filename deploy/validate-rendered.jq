def workload: .kind == "Deployment" or .kind == "StatefulSet";
def pod_specs: [.[] | select(workload) | .spec.template.spec];
def containers: [.[] | ((.initContainers // []) + .containers)[]];

# Input is an array of the rendered application and load-generator objects.
type == "array" and
all(.[];
  (.kind | IN("Deployment", "StatefulSet", "Service", "PersistentVolumeClaim")) and
  ((.metadata.namespace // "robot-shop") == "robot-shop")
) and
all(.[] | select(.kind == "Service");
  ((.spec.type // "ClusterIP") == "ClusterIP") and
  ((.spec.externalIPs // []) | length == 0)
) and
all(.[] | select(workload); (.spec.replicas // 1) == 1) and
(pod_specs |
  length == 13 and
  all(.[];
    .automountServiceAccountToken == false and
    ((.hostNetwork // false) == false) and
    ((.hostPID // false) == false) and
    ((.hostIPC // false) == false) and
    all((.volumes // [])[]; has("hostPath") | not)
  ) and
  (containers |
    length == 13 and
    all(.[];
      (.image | test("@sha256:[a-f0-9]{64}$")) and
      ((.securityContext.privileged // false) == false) and
      ((.securityContext.capabilities.add // []) | length == 0) and
      all((.env // [])[]; (.name | test("^(INSTANA|EUM)_") | not)) and
      (.resources.requests.cpu != null) and
      (.resources.requests.memory != null) and
      (.resources.limits.cpu != null) and
      (.resources.limits.memory != null) and
      all((.ports // [])[]; (.hostPort // 0) == 0)
    )
  )
)
