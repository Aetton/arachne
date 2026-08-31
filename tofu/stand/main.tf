# Ephemeral stand provisioning for Arachne.
#
# The golden template is the source of truth for VM hardware, disks, network and
# guest configuration. Arachne only chooses the template and the target VM name.
#
# Credentials and endpoint are intentionally not stored here. bpg/proxmox reads
# PROXMOX_VE_ENDPOINT and PROXMOX_VE_API_TOKEN (or username/password) from the
# environment inherited by the tofu-proxmox spider.

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.60"
    }
  }
}

provider "proxmox" {}

variable "stand_name" {
  type = string
}

variable "os" {
  type = string
}

variable "template_vm_id" {
  type = number
}

# Node where the cloned VM will live.
variable "node_name" {
  type = string
}

# Source node of the template. Leave empty when the template is on node_name.
variable "template_node_name" {
  type    = string
  default = ""
}

# Optional target datastore for the clone. Empty means inherit the template
# storage placement. Set this when cloning across nodes with non-shared storage.
variable "clone_datastore_id" {
  type    = string
  default = ""
}

resource "proxmox_virtual_environment_vm" "stand" {
  name      = var.stand_name
  node_name = var.node_name
  started   = true

  clone {
    vm_id        = var.template_vm_id
    node_name    = var.template_node_name != "" ? var.template_node_name : null
    datastore_id = var.clone_datastore_id != "" ? var.clone_datastore_id : null
    full          = true
  }

  # Golden templates must have qemu-guest-agent installed. Keeping it enabled
  # lets the provider expose ipv4_addresses so Arachne can hand the VM to the
  # next step without hard-coded addressing.
  agent {
    enabled = true
  }

  tags = ["arachne", "ephemeral", var.os]
}

locals {
  vm_ipv4_addresses = [
    for ip in flatten(proxmox_virtual_environment_vm.stand.ipv4_addresses) : ip
    if ip != "" && ip != "127.0.0.1"
  ]
}

output "vm_id" {
  value = proxmox_virtual_environment_vm.stand.vm_id
}

output "vm_ip" {
  value = try(local.vm_ipv4_addresses[0], "")
}
