output "instance_id" {
  description = "For `aws ec2 stop-instances --instance-ids ...` at the end of the day."
  value       = aws_instance.bastion.id
}

output "public_ip" {
  description = <<-EOT
    Current public address.

    This CHANGES every time the instance is stopped and started. After a start,
    fetch the new one rather than trusting a stale value:

        aws ec2 describe-instances --instance-ids <id> \
          --query 'Reservations[0].Instances[0].PublicIpAddress' --output text

    An Elastic IP would keep it stable, but AWS charges for every public IPv4
    address whether it is attached or not — and an orphaned Elastic IP quietly
    billing for nothing is a mistake this project has already made once.
  EOT
  value       = aws_instance.bastion.public_ip
}

output "ssh_command" {
  description = "Plain shell access to the bastion."
  value       = "ssh -i ~/.ssh/sportable ec2-user@${aws_instance.bastion.public_ip}"
}
