# dir-canary
Do something when files are added to a remote host.

Two Python scripts (daemonized): 

1. dirCanary.py running on a BSD internet-facing gateway, waiting for files to be added to directories.

2. dirCanaryListener.py running on a Linux fileserver behind the gateway, waiting for a TCP packet from dirCanary.py so that it can execute a shell command on the fileserver. 


In my case, Android devices sync photos and videos to the gateway over SFTP. The gateway notifies the fileserver which fetches the files off the gateway (SFTP). "batch.txt" is the list of SFTP commands the fileserver executes once connected to the gateway.


The daemons should run unpriviledged and the SFTP logins on the BSD gateway should be chroot'd without a shell. 

Only the BSD gateway should be accessible from the internet.

No new server ports opened on the BSD gateway (SSH only).  

SSH and dirCanary ports listening on the fileserver.


