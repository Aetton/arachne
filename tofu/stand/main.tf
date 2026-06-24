# OpenTofu stand provisioning (Proxmox). Stub — wire up your provider creds.
#
#   tofu init && tofu apply -var stand_name=test-stand -var version=1.0.5

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.60"
    }
  }
}

variable "stand_name" { type = string }
variable "version"    { type = string, default = "0.0.0" }

# provider "proxmox" {
#   endpoint = "https://proxmox.redsoft.internal:8006/"
#   # api_token / ssh creds via env: PROXMOX_VE_API_TOKEN etc.
# }

# resource "proxmox_virtual_environment_vm" "stand" {
#   name      = var.stand_name
#   node_name = "pve"
#   clone { vm_id = 9000 }   # template id
#   ...
# }

output "vm_ip" {
  value = "10.81.19.200"   # replace with proxmox_..._vm.stand.ipv4_addresses
}
