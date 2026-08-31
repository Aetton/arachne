# Ephemeral stand provisioning for Arachne.
#
# The golden template is the source of truth. Optional resource overrides are
# applied only when the scenario explicitly asks for them. Scenario authors never
# need to know Proxmox nodes, VM IDs, datastores or disk interfaces.
#
# Credentials and endpoint are intentionally not stored here. bpg/proxmox reads
# PROXMOX_VE_ENDPOINT and PROXMOX_VE_API_TOKEN from the inherited environment.

terraform {
  required_providers {
    proxmox = {
      source  = "registry.terraform.io/bpg/proxmox"
      version = "= 0.111.1"
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

variable "node_name" {
  type = string
}

variable "template_node_name" {
  type    = string
  default = ""
}

variable "clone_datastore_id" {
  type    = string
  default = ""
}

variable "override_cpu" {
  type    = number
  default = null
}

variable "override_memory_mb" {
  type    = number
  default = null
}

variable "override_disk_gb" {
  type    = number
  default = null
}

variable "override_disk_interface" {
  type    = string
  default = ""
}

variable "override_disk_datastore_id" {
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

  # Runtime stands expose a SPICE console regardless of the golden image's
  # display adapter. QXL enables Proxmox spiceproxy and fresh .vv downloads.
  vga {
    type = "qxl"
  }

  # No block means inherit that resource dimension from the golden template.
  dynamic "cpu" {
    for_each = var.override_cpu == null ? [] : [var.override_cpu]
    content {
      cores = cpu.value
    }
  }

  dynamic "memory" {
    for_each = var.override_memory_mb == null ? [] : [var.override_memory_mb]
    content {
      dedicated = memory.value
    }
  }

  # Disk growth is backend-resolved: the scenario gives only the desired size,
  # while Arachne supplies the template's datastore and system-disk interface.
  dynamic "disk" {
    for_each = var.override_disk_gb == null ? [] : [var.override_disk_gb]
    content {
      datastore_id = var.override_disk_datastore_id
      interface    = var.override_disk_interface
      size         = disk.value
    }
  }

  agent {
    enabled = true
  }

  # Keep the golden-image tag set untouched. Managing registered Proxmox tags
  # requires Sys.Modify on '/', which is intentionally outside the Arachne role.
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
