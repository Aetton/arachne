# Ephemeral stand provisioning for Arachne.
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

variable "node_name" {
  type    = string
  default = "pve"
}

variable "datastore_id" {
  type    = string
  default = "local-lvm"
}

variable "bridge" {
  type    = string
  default = "vmbr0"
}

variable "disk_interface" {
  type    = string
  default = "scsi0"
}

variable "vcpus" {
  type    = number
  default = 4
}

variable "ram_mb" {
  type    = number
  default = 8192
}

variable "disk_gb" {
  type    = number
  default = 40
}

resource "proxmox_virtual_environment_vm" "stand" {
  name      = var.stand_name
  node_name = var.node_name

  clone {
    vm_id        = var.template_vm_id
    datastore_id = var.datastore_id
  }

  agent {
    enabled = true
  }

  cpu {
    cores = var.vcpus
  }

  memory {
    dedicated = var.ram_mb
  }

  # CI templates are expected to expose their system disk on disk_interface.
  # OpenTofu may grow that disk, but Proxmox cannot shrink it below the template
  # size. Keep template disks deliberately small.
  disk {
    datastore_id = var.datastore_id
    interface    = var.disk_interface
    size         = var.disk_gb
  }

  network_device {
    bridge = var.bridge
  }

  # Linux templates need cloud-init; Windows templates need an equivalent
  # Cloudbase-Init setup. DHCP plus qemu-guest-agent gives Arachne the resulting
  # address without baking an IP into the template.
  initialization {
    datastore_id = var.datastore_id

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
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
