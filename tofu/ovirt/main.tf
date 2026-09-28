terraform {
  required_providers {
    ovirt = {
      source  = "registry.terraform.io/ovirt/ovirt"
      version = "= 2.2.0"
    }
  }
}
variable "ovirt_url" { type = string }
variable "ovirt_username" { type = string }
variable "ovirt_password" {
  type      = string
  sensitive = true
}
variable "ovirt_insecure" {
  type    = bool
  default = false
}
variable "ovirt_ca_file" {
  type    = string
  default = ""
}
provider "ovirt" {
  url          = "${trimsuffix(var.ovirt_url, "/")}/"
  username     = var.ovirt_username
  password     = var.ovirt_password
  tls_insecure = var.ovirt_insecure
  tls_system   = var.ovirt_insecure ? null : true
  tls_ca_files = var.ovirt_insecure || var.ovirt_ca_file == "" ? null : [var.ovirt_ca_file]
}
variable "stand_name" { type = string }
variable "template_id" { type = string }
variable "cluster_id" { type = string }
variable "cpu" { type = number }
variable "memory" { type = number }

# Golden templates supply disks and NICs, including their vNIC profiles.
resource "ovirt_vm" "stand" {
  name           = var.stand_name
  template_id    = var.template_id
  cluster_id     = var.cluster_id
  clone          = true
  cpu_cores      = var.cpu
  cpu_sockets    = 1
  cpu_threads    = 1
  memory         = var.memory
  maximum_memory = var.memory
}
resource "ovirt_vm_start" "stand" {
  vm_id         = ovirt_vm.stand.id
  stop_behavior = "stop"
  force_stop    = true
}
output "vm_id" { value = ovirt_vm.stand.id }
# Guest discovery runs after apply, with explicit IPv4/interface/CIDR selection.
# This avoids wait_for_ip accepting an unrelated bridge or IPv6 address.
output "vm_ip" { value = "" }
