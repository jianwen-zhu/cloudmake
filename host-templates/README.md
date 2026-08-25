# SSH host alias templates

These files are editable examples for Cloudmake's `ssh` / `host-ssh` backend.
Cloudmake installs and prints them, but never changes `~/.ssh/config`, creates a
key, or copies credentials.

List and render the installed templates:

```sh
cloudmake --host-templates
cloudmake --host-template generic
cloudmake --host-template oci-always-free
cloudmake --host-template gcp-e2-micro
```

## Safe installation

OpenSSH reads configuration from the first value it obtains for each setting.
Review existing configuration before adding an `Include` directive or alias.

1. Create a private fragment directory:

   ```sh
   mkdir -p ~/.ssh/config.d
   chmod 700 ~/.ssh ~/.ssh/config.d
   ```

2. Render a template with private file permissions and edit every
   `REPLACE_WITH` placeholder:

   ```sh
   umask 077
   cloudmake --host-template oci-always-free > ~/.ssh/config.d/oci-free.conf
   ${EDITOR:-vi} ~/.ssh/config.d/oci-free.conf
   chmod 600 ~/.ssh/config.d/oci-free.conf
   ```

3. If the main `~/.ssh/config` does not already include that directory, add this
   line yourself near the beginning of the file:

   ```sshconfig
   Include ~/.ssh/config.d/*.conf
   ```

4. Verify host identity and connectivity directly before Cloudmake's
   non-interactive doctor check:

   ```sh
   ssh oci-free true
   cloudmake -b ssh --host oci-free --doctor
   cloudmake --use ssh --host oci-free
   ```

Never add `StrictHostKeyChecking no` or put private-key contents, passwords, or
tokens in these files. `IdentityFile` contains only the path to a key that
OpenSSH continues to own.

## Provider notes

- OCI Ubuntu images normally use `ubuntu`; Oracle Linux images normally use
  `opc`. See Oracle's [Linux instance connection
  guide](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/connect-to-linux-instance.htm).
- Google recommends `gcloud compute config-ssh` when it manages instance SSH
  keys. That command creates `NAME.ZONE.PROJECT` aliases which can be passed
  directly to `cloudmake --host`. See the [`gcloud compute config-ssh`
  reference](https://docs.cloud.google.com/sdk/gcloud/reference/compute/config-ssh).
- Codespaces, paid Colab SSH, and Lightning use their dedicated Cloudmake
  backends because their provider clients discover or generate the connection.
  They do not use these static templates.
